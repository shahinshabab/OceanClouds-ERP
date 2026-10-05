from datetime import timedelta
from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from common.models import UserLoginSession, UserSessionEndReason
from common.session_management import close_expired_login_sessions
from common.test_helpers import make_user
from projects.models import Project, Task, TaskStatus, WorkSession, WorkSessionStatus
from reports.utils import _build_attendance_summary

IDLE = 30 * 60


@override_settings(LOGIN_IDLE_TIMEOUT_SECONDS=IDLE)
class IdleLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user(username="idle-user")
        self.client.force_login(self.user)
        self.session_key = self.client.session.session_key
        self.now = timezone.now()
        self.login = UserLoginSession.objects.get(user=self.user, logout_at__isnull=True)
        self.login.login_at = self.now - timedelta(hours=6)
        self.login.save(update_fields=["login_at"])

    def set_last_activity(self, ago):
        self.login.last_activity_at = self.now - ago
        self.login.save(update_fields=["last_activity_at"])
        return self.login.last_activity_at

    def test_idle_login_ends_at_last_activity_without_review(self):
        last_activity = self.set_last_activity(timedelta(minutes=31))
        project = Project.objects.create(name="Idle project")
        task = Task.objects.create(project=project, name="Idle task", status=TaskStatus.IN_PROGRESS)
        work = WorkSession.objects.create(
            user=self.user,
            project=project,
            task=task,
            started_at=last_activity - timedelta(hours=1),
            last_resumed_at=last_activity - timedelta(hours=1),
        )

        closed = close_expired_login_sessions(now=self.now)

        self.login.refresh_from_db()
        work.refresh_from_db()
        self.assertEqual(closed, [self.session_key])
        self.assertEqual(self.login.end_reason, UserSessionEndReason.IDLE_TIMEOUT)
        self.assertEqual(self.login.logout_at, last_activity)
        self.assertEqual(self.login.checkout_review_status, "not_required")
        self.assertFalse(Session.objects.filter(session_key=self.session_key).exists())
        self.assertEqual(work.status, WorkSessionStatus.PAUSED)
        self.assertEqual(work.paused_at, last_activity)
        self.assertEqual(work.work_seconds, 60 * 60)

    def test_recent_activity_keeps_login_open(self):
        self.set_last_activity(timedelta(minutes=29))

        self.assertEqual(close_expired_login_sessions(now=self.now), [])
        self.login.refresh_from_db()
        self.assertTrue(self.login.is_active)

    @override_settings(LOGIN_IDLE_TIMEOUT_SECONDS=0)
    def test_zero_turns_idle_logout_off(self):
        self.set_last_activity(timedelta(hours=4))

        self.assertEqual(close_expired_login_sessions(now=self.now), [])

    def test_activity_through_fixed_deadline_still_ends_at_deadline(self):
        self.login.expires_at = self.now - timedelta(minutes=5)
        self.login.last_activity_at = self.now - timedelta(minutes=20)
        self.login.save(update_fields=["expires_at", "last_activity_at"])

        close_expired_login_sessions(now=self.now)

        self.login.refresh_from_db()
        self.assertEqual(self.login.end_reason, UserSessionEndReason.SESSION_EXPIRED)
        self.assertEqual(self.login.logout_at, self.login.expires_at)
        self.assertEqual(self.login.checkout_review_status, "pending")

    def test_going_idle_before_fixed_deadline_is_an_idle_logout(self):
        self.login.expires_at = self.now - timedelta(minutes=5)
        last_activity = self.now - timedelta(hours=1)
        self.login.last_activity_at = last_activity
        self.login.save(update_fields=["expires_at", "last_activity_at"])

        close_expired_login_sessions(now=self.now)

        self.login.refresh_from_db()
        self.assertEqual(self.login.end_reason, UserSessionEndReason.IDLE_TIMEOUT)
        self.assertEqual(self.login.logout_at, last_activity)

    def test_returning_after_idle_timeout_requires_sign_in(self):
        self.set_last_activity(timedelta(minutes=45))

        response = self.client.get(reverse("ui:home"))

        self.login.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("ui:login"), response["Location"])
        self.assertEqual(self.login.end_reason, UserSessionEndReason.IDLE_TIMEOUT)

    def test_user_navigation_counts_as_activity(self):
        old = self.set_last_activity(timedelta(minutes=10))

        self.client.get(
            reverse("ui:home"),
            headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-User": "?1"},
        )

        self.login.refresh_from_db()
        self.assertGreater(self.login.last_activity_at, old)

    def test_automatic_requests_do_not_count_as_activity(self):
        old = self.set_last_activity(timedelta(minutes=10))

        # A live-update reload, and a background fetch for the bell.
        self.client.get(reverse("ui:home"), headers={"Sec-Fetch-Mode": "navigate"})
        self.client.get(
            reverse("common:notification_panel"),
            headers={"Sec-Fetch-Mode": "cors"},
        )

        self.login.refresh_from_db()
        self.assertEqual(self.login.last_activity_at, old)

    def test_heartbeat_after_idle_timeout_signs_out_with_reason(self):
        last_activity = self.set_last_activity(timedelta(minutes=31))

        with patch("common.views.timezone.now", return_value=self.now):
            response = self.client.post(reverse("common:session_heartbeat"))

        self.login.refresh_from_db()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["reason"], "idle_timeout")
        self.assertEqual(self.login.logout_at, last_activity)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_heartbeat_after_cleanup_still_reports_reason(self):
        self.set_last_activity(timedelta(minutes=31))
        close_expired_login_sessions(now=self.now)

        response = self.client.post(reverse("common:session_heartbeat"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["reason"], "idle_timeout")

    def test_login_page_explains_idle_sign_out(self):
        self.client.logout()

        response = self.client.get(reverse("ui:login"), {"ended": "idle_timeout"})

        self.assertContains(response, "signed out after 30 minutes of inactivity")


class IdleLogoutAttendanceTests(TestCase):
    def test_idle_logout_counts_until_last_activity(self):
        user = make_user(username="idle-attendance-user")
        login_at = timezone.now().replace(hour=1, minute=0, second=0, microsecond=0)
        UserLoginSession.objects.create(
            user=user,
            session_key="idle-attendance",
            login_at=login_at,
            last_activity_at=login_at + timedelta(hours=8, minutes=30),
            logout_at=login_at + timedelta(hours=8, minutes=30),
            end_reason=UserSessionEndReason.IDLE_TIMEOUT,
        )
        day = timezone.localtime(login_at).date()

        summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user=user), day, day,
        )

        self.assertEqual(summary["attendance_days"], 1)
        self.assertEqual(summary["days"][0]["hm"], "8h 30m")


class DefaultSessionLimitTests(TestCase):
    def test_idle_sign_out_is_off_by_default(self):
        from django.conf import settings

        self.assertEqual(settings.LOGIN_IDLE_TIMEOUT_SECONDS, 0)
        self.assertEqual(settings.LOGIN_SESSION_MAX_SECONDS, 12 * 60 * 60)

        user = make_user(username="long-idle-user")
        self.client.force_login(user)
        UserLoginSession.objects.filter(user=user).update(
            last_activity_at=timezone.now() - timedelta(hours=3),
        )

        close_expired_login_sessions()

        self.assertTrue(UserLoginSession.objects.filter(user=user, logout_at__isnull=True).exists())
