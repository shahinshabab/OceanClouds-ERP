from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from common.browser_presence import session_presence
from common.models import ImportantNotice, UserLoginSession
from common.roles import ROLE_EMPLOYEE
from common.test_helpers import make_user
from projects.models import Project, Task, WorkSession, WorkSessionStatus


class BrowserHeartbeatTests(TestCase):
    def setUp(self):
        self.user = make_user(username="presence-user")
        self.user.groups.add(Group.objects.get_or_create(name=ROLE_EMPLOYEE)[0])
        self.client.force_login(self.user)
        self.login = UserLoginSession.objects.get(user=self.user, logout_at__isnull=True)
        self.url = reverse("common:session_heartbeat")
        self.now = timezone.now()
        self.login.last_activity_at = self.now - timedelta(minutes=4)
        self.login.save(update_fields=["last_activity_at"])

    def heartbeat(self, **data):
        with patch("common.views.timezone.now", return_value=self.now):
            return self.client.post(self.url, data)

    def test_updates_existing_row_with_server_time_without_extending_login(self):
        expires_at = self.login.expires_at
        login_at = self.login.login_at
        project = Project.objects.create(name="Presence work")
        task = Task.objects.create(project=project, name="Presence task")
        work = WorkSession.objects.create(user=self.user, project=project, task=task)

        response = self.heartbeat(last_activity_at="2099-01-01", user_id="99999")

        self.assertEqual(response.status_code, 204)
        self.assertIn("no-store", response["Cache-Control"])
        self.login.refresh_from_db()
        work.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, self.now)
        self.assertEqual(self.login.login_at, login_at)
        self.assertEqual(self.login.expires_at, expires_at)
        self.assertIsNone(self.login.logout_at)
        self.assertEqual(self.login.checkout_review_status, "not_required")
        self.assertEqual(work.status, WorkSessionStatus.ACTIVE)
        self.assertEqual(UserLoginSession.objects.filter(user=self.user).count(), 1)

    def test_duplicate_requests_do_not_write_another_timestamp(self):
        self.assertEqual(self.heartbeat().status_code, 204)
        self.now += timedelta(seconds=59)
        self.assertEqual(self.heartbeat().status_code, 204)
        self.login.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, self.now - timedelta(seconds=59))
        self.now += timedelta(seconds=1)
        self.assertEqual(self.heartbeat().status_code, 204)
        self.login.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, self.now)

    def test_endpoint_skips_global_cleanup_and_notice_queries(self):
        ImportantNotice.objects.create(key="presence-notice", title="Policy", body="Read this.")
        with patch("common.middleware.close_expired_login_sessions") as cleanup, CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.heartbeat().status_code, 204)
        cleanup.assert_not_called()
        self.assertFalse(any("common_importantnotice" in query["sql"] for query in queries))

    def test_anonymous_and_non_post_requests_cannot_update_presence(self):
        original = self.login.last_activity_at
        self.assertEqual(Client().post(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.login.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, original)

    def test_expired_deadline_is_rejected_without_marking_manual_logout(self):
        self.login.expires_at = self.now
        self.login.save(update_fields=["expires_at"])
        original = self.login.last_activity_at

        self.assertEqual(self.heartbeat().status_code, 401)

        self.login.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, original)
        self.assertIsNone(self.login.logout_at)

    def test_closed_row_is_not_reopened(self):
        self.login.close()
        original = self.login.last_activity_at

        self.assertEqual(self.heartbeat().status_code, 401)

        self.login.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, original)
        self.assertEqual(self.login.end_reason, "logout")

    def test_replaced_browser_cannot_refresh_current_session(self):
        current_browser = Client()
        current_browser.force_login(self.user)
        current = UserLoginSession.objects.get(user=self.user, logout_at__isnull=True)
        original = current.last_activity_at

        self.assertEqual(self.heartbeat().status_code, 401)

        current.refresh_from_db()
        self.assertEqual(current.last_activity_at, original)
        self.assertIsNone(current.logout_at)

    def test_csrf_is_required_for_fetch_and_beacon_form_posts(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        page = browser.get(reverse("ui:home"))
        self.assertContains(page, "ui/browser_presence.js")
        self.assertEqual(browser.post(self.url).status_code, 403)
        self.assertEqual(
            browser.post(self.url, {"csrfmiddlewaretoken": browser.cookies["csrftoken"].value}).status_code,
            204,
        )

    def test_script_included_in_authenticated_app_and_admin_only(self):
        self.assertContains(self.client.get(reverse("ui:home")), "ui/browser_presence.js")
        self.assertContains(self.client.get(reverse("admin:password_change")), "ui/browser_presence.js")
        self.assertNotContains(Client().get(reverse("ui:login")), "ui/browser_presence.js")

    def test_attendance_shows_offline_estimate_separate_from_checkout(self):
        reviewer = make_user(username="presence-reviewer", is_superuser=True)
        self.client.force_login(reviewer)
        response = self.client.get(reverse("reports:attendance"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Offline (estimated)")
        self.assertContains(response, "Last seen:")
        self.assertContains(response, "Offline since:")
        self.assertContains(response, "Not checked out")
        self.login.refresh_from_db()
        self.assertIsNone(self.login.logout_at)

    def test_returning_user_is_online_on_their_attendance_page(self):
        response = self.client.get(reverse("reports:attendance"))

        self.assertContains(response, ">Online</span>")
        self.assertNotContains(response, "Offline (estimated)")


class BrowserPresenceStateTests(TestCase):
    def test_offline_boundary_and_returning_browser(self):
        now = timezone.now()
        login = UserLoginSession(last_activity_at=now - timedelta(seconds=179))
        self.assertEqual(session_presence(login, now)["status"], "online")
        presence = session_presence(login, now + timedelta(seconds=1))
        self.assertEqual(presence["status"], "offline")
        self.assertEqual(presence["offline_since"], now + timedelta(seconds=1))
        login.last_activity_at = now
        self.assertEqual(session_presence(login, now)["status"], "online")

    def test_logout_and_fixed_expiry_are_ended_even_with_recent_activity(self):
        now = timezone.now()
        login = UserLoginSession(last_activity_at=now, logout_at=now)
        self.assertEqual(session_presence(login, now)["status"], "ended")
        login.logout_at = None
        login.expires_at = now
        self.assertEqual(session_presence(login, now)["status"], "ended")
