from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from common.middleware import CloseExpiredLoginSessionsMiddleware
from common.role_permissions import setup_role_groups
from common.roles import ROLE_ADMIN, ROLE_CRM_MANAGER, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER
from common.test_helpers import AuthenticatedViewTestMixin, make_user
from common.notifications import notify_user
from projects.models import Project, Task, TaskStatus, WorkSession, WorkSessionStatus

from .models import (
    Choice,
    Communication,
    ImportantNotice,
    Notification,
    UserLoginSession,
    UserNoticeAcknowledgement,
)


class CommonModelTests(AuthenticatedViewTestMixin):
    list_url_names = ["common:notification_list"]

    def test_choice_string_and_unique_type_value(self):
        Choice.objects.create(type="lead_source", value="Instagram")

        with self.assertRaises(IntegrityError):
            Choice.objects.create(type="lead_source", value="Instagram")

    def test_communication_string_uses_channel_display(self):
        communication = Communication.objects.create(
            channel="email",
            subject="Welcome",
        )

        self.assertEqual(str(communication), "Email - Welcome")

    def test_notification_target_url_uses_target_absolute_url(self):
        recipient = make_user(username="notify-user")
        choice = Choice.objects.create(type="source", value="Website")
        notification = Notification.objects.create(
            recipient=recipient,
            notif_type=Notification.Type.LEAD_FOLLOW_UP,
            target=choice,
            message="Follow up",
        )

        self.assertEqual(str(notification), "Follow up")
        self.assertEqual(notification.get_target_url(), "#")

    def test_notification_dedupe_key_is_unique_per_recipient(self):
        recipient = make_user(username="dedupe-user")
        Notification.objects.create(
            recipient=recipient,
            notif_type=Notification.Type.TASK_DUE,
            dedupe_key="task:1",
        )

        with self.assertRaises(IntegrityError):
            Notification.objects.create(
                recipient=recipient,
                notif_type=Notification.Type.TASK_DUE,
                dedupe_key="task:1",
            )

    def test_duplicate_notifications_get_unique_dedupe_keys(self):
        recipient = make_user(username="duplicate-notify-user")
        choice = Choice.objects.create(type="source", value="Referral")

        first = notify_user(
            recipient=recipient,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            target=choice,
            message="Assigned once",
            allow_duplicate=True,
        )
        second = notify_user(
            recipient=recipient,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            target=choice,
            message="Assigned again",
            allow_duplicate=True,
        )

        self.assertIsNotNone(first.dedupe_key)
        self.assertIsNotNone(second.dedupe_key)
        self.assertNotEqual(first.dedupe_key, second.dedupe_key)

    def test_login_session_duration_and_close(self):
        user = make_user(username="session-user")
        session = UserLoginSession.objects.create(
            user=user,
            session_key="abc",
            login_at=timezone.now() - timedelta(hours=2),
        )

        self.assertTrue(session.is_active)
        self.assertGreaterEqual(session.duration_seconds, 7200)

        session.close()
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertEqual(session.end_reason, "logout")

    def test_login_receives_fixed_sixteen_hour_deadline(self):
        user = make_user(username="fixed-deadline-user")
        browser = Client()

        self.assertTrue(browser.login(username=user.username, password="pass12345"))
        login_session = UserLoginSession.objects.get(user=user, logout_at__isnull=True)

        self.assertEqual(
            login_session.expires_at - login_session.login_at,
            timedelta(hours=16),
        )

    def test_absolute_expiry_pauses_work_at_session_deadline(self):
        user = make_user(username="stale-session-user")
        now = timezone.now()
        expires_at = now - timedelta(minutes=1)
        login_session = UserLoginSession.objects.create(
            user=user,
            session_key="missing-session-key",
            login_at=now - timedelta(hours=16, minutes=1),
            last_activity_at=now - timedelta(minutes=5),
            expires_at=expires_at,
        )
        project = Project.objects.create(name="Timed Out Project")
        task = Task.objects.create(
            project=project,
            name="Timed Out Task",
            status=TaskStatus.IN_PROGRESS,
        )
        work_session = WorkSession.objects.create(
            user=user,
            project=project,
            task=task,
            started_at=expires_at - timedelta(hours=2),
            last_resumed_at=expires_at - timedelta(hours=2),
        )
        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.user = AnonymousUser()
        middleware = CloseExpiredLoginSessionsMiddleware(lambda request: None)

        middleware(request)

        login_session.refresh_from_db()
        work_session.refresh_from_db()
        task.refresh_from_db()
        self.assertFalse(login_session.is_active)
        self.assertEqual(login_session.end_reason, "session_expired")
        self.assertEqual(login_session.checkout_review_status, "pending")
        self.assertEqual(login_session.logout_at, expires_at)
        self.assertEqual(work_session.status, WorkSessionStatus.PAUSED)
        self.assertEqual(work_session.paused_at, expires_at)
        self.assertEqual(work_session.work_seconds, 2 * 60 * 60)
        self.assertEqual(task.status, TaskStatus.PAUSED)

    def test_session_before_absolute_deadline_is_not_expired(self):
        user = make_user(username="recently-active-user")
        now = timezone.now()
        expires_at = now + timedelta(hours=8)
        login_session = UserLoginSession.objects.create(
            user=user,
            session_key="recent-session-key",
            login_at=now - timedelta(hours=8),
            last_activity_at=now - timedelta(hours=4),
            expires_at=expires_at,
        )
        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.user = AnonymousUser()

        CloseExpiredLoginSessionsMiddleware(lambda request: None)(request)

        login_session.refresh_from_db()
        self.assertTrue(login_session.is_active)
        self.assertEqual(login_session.expires_at, expires_at)

    def test_expired_current_request_is_logged_out_before_protected_view(self):
        user = make_user(username="idle-current-user")
        browser = Client()
        browser.force_login(user)
        login_session = UserLoginSession.objects.get(
            user=user,
            logout_at__isnull=True,
        )
        login_session.expires_at = timezone.now() - timedelta(seconds=1)
        login_session.save(update_fields=["expires_at"])

        response = browser.get(reverse("ui:home"))

        login_session.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("ui:login"), response["Location"])
        self.assertEqual(login_session.end_reason, "session_expired")
        self.assertNotIn("_auth_user_id", browser.session)

    def test_mark_notification_read_url_reverses(self):
        recipient = make_user(username="mark-read-user")
        notification = Notification.objects.create(
            recipient=recipient,
            notif_type=Notification.Type.EVENT_REMINDER,
        )

        self.assertEqual(
            reverse("common:notification_mark_read", args=[notification.pk]),
            f"/common/notifications/{notification.pk}/mark-read/",
        )


class RolePermissionSetupTests(TestCase):
    def test_setup_role_groups_creates_expected_groups(self):
        Group.objects.create(name="Manager")

        setup_role_groups()

        self.assertTrue(Group.objects.filter(name=ROLE_ADMIN).exists())
        self.assertTrue(Group.objects.filter(name=ROLE_CRM_MANAGER).exists())
        self.assertTrue(Group.objects.filter(name=ROLE_PROJECT_MANAGER).exists())
        self.assertTrue(Group.objects.filter(name=ROLE_EMPLOYEE).exists())
        self.assertFalse(Group.objects.filter(name="Manager").exists())

    def test_setup_role_groups_assigns_suitable_permissions(self):
        setup_role_groups()

        admin = Group.objects.get(name=ROLE_ADMIN)
        crm_manager = Group.objects.get(name=ROLE_CRM_MANAGER)
        project_manager = Group.objects.get(name=ROLE_PROJECT_MANAGER)
        employee = Group.objects.get(name=ROLE_EMPLOYEE)

        add_client = Permission.objects.get(
            content_type__app_label="crm",
            codename="add_client",
        )
        add_service = Permission.objects.get(
            content_type__app_label="services",
            codename="add_service",
        )
        change_project = Permission.objects.get(
            content_type__app_label="projects",
            codename="change_project",
        )
        view_project = Permission.objects.get(
            content_type__app_label="projects",
            codename="view_project",
        )
        review_attendance = Permission.objects.get(
            content_type__app_label="common",
            codename="review_attendance",
        )
        review_leave = Permission.objects.get(
            content_type__app_label="common",
            codename="review_leave_requests",
        )

        self.assertIn(add_service, admin.permissions.all())
        self.assertIn(add_client, crm_manager.permissions.all())
        self.assertNotIn(add_service, crm_manager.permissions.all())
        self.assertIn(change_project, project_manager.permissions.all())
        self.assertIn(review_attendance, project_manager.permissions.all())
        self.assertIn(review_leave, project_manager.permissions.all())
        self.assertIn(view_project, employee.permissions.all())
        self.assertNotIn(review_attendance, employee.permissions.all())
        self.assertNotIn(change_project, employee.permissions.all())


class ImportantNoticeTests(TestCase):
    def setUp(self):
        self.user = make_user(username="notice-user")
        self.notice = ImportantNotice.objects.create(
            key="required-policy",
            title="Required Policy",
            body="Please read this important policy.",
        )
        self.client.force_login(self.user)

    def test_required_notice_blocks_application_until_agreed(self):
        response = self.client.get(reverse("ui:home"))

        self.assertRedirects(
            response,
            f'{reverse("common:important_notice")}?next=/',
            fetch_redirect_response=False,
        )
        notice_response = self.client.get(reverse("common:important_notice"))
        self.assertEqual(notice_response.status_code, 200)
        self.assertContains(notice_response, "Required Policy")
        self.assertContains(notice_response, "I have read and agree")

        agreement_response = self.client.post(
            reverse("common:important_notice"),
            {"next": reverse("ui:home")},
        )
        self.assertRedirects(agreement_response, reverse("ui:home"))
        self.assertTrue(
            UserNoticeAcknowledgement.objects.filter(
                notice=self.notice,
                user=self.user,
            ).exists()
        )

    def test_inactive_notice_does_not_block(self):
        self.notice.is_active = False
        self.notice.save(update_fields=["is_active"])

        response = self.client.get(reverse("ui:home"))

        self.assertEqual(response.status_code, 200)

    def test_attendance_notice_publish_command_is_idempotent(self):
        self.notice.delete()
        output = StringIO()

        call_command("publish_attendance_notice", stdout=output)
        call_command("publish_attendance_notice", stdout=output)

        self.assertEqual(
            ImportantNotice.objects.filter(key="attendance-session-policy-2026-08").count(),
            1,
        )
