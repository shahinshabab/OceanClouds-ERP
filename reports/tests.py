from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from common.models import (
    CheckoutReviewStatus,
    LeaveRequest,
    LeaveStatus,
    UserLoginSession,
    UserSessionEndReason,
)
from common.roles import ROLE_ADMIN, ROLE_CRM_MANAGER, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER
from common.test_helpers import AuthenticatedViewTestMixin, make_user
from projects.models import Project, Task, TaskStatus, WorkSession, WorkSessionStatus

from .utils import (
    _build_attendance_summary,
    _build_login_month_table,
    _format_seconds_hm,
    _sum_work_session_seconds,
)


class ReportsViewTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "reports:dashboard",
        "reports:sales_report",
        "reports:project_report",
        "reports:employee_work_report",
        "reports:attendance",
    ]


class EmployeeReportCalculationTests(TestCase):
    @override_settings(TIME_ZONE="Asia/Kolkata", USE_TZ=True)
    def test_attendance_requires_eight_hours_of_used_login_time(self):
        user = make_user(username="attendance-user")
        kolkata = ZoneInfo("Asia/Kolkata")

        def aware(year, month, day, hour, minute=0):
            return timezone.make_aware(
                datetime(year, month, day, hour, minute),
                kolkata,
            )

        UserLoginSession.objects.create(
            user=user,
            session_key="seven-hours",
            login_at=aware(2026, 7, 1, 9),
            logout_at=aware(2026, 7, 1, 16),
            end_reason=UserSessionEndReason.LOGOUT,
        )
        UserLoginSession.objects.create(
            user=user,
            session_key="manual-part-one",
            login_at=aware(2026, 7, 2, 9),
            logout_at=aware(2026, 7, 2, 13),
            end_reason=UserSessionEndReason.LOGOUT,
        )
        UserLoginSession.objects.create(
            user=user,
            session_key="manual-part-two",
            login_at=aware(2026, 7, 2, 14),
            logout_at=aware(2026, 7, 2, 18),
            end_reason=UserSessionEndReason.LOGOUT,
        )
        UserLoginSession.objects.create(
            user=user,
            session_key="auto-timeout",
            login_at=aware(2026, 7, 3, 9),
            logout_at=aware(2026, 7, 3, 18),
            end_reason=UserSessionEndReason.AUTO_TIMEOUT,
        )

        summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user=user),
            datetime(2026, 7, 1).date(),
            datetime(2026, 7, 3).date(),
        )

        self.assertEqual(summary["attendance_days"], 1)
        self.assertEqual(summary["days"][0]["date"], datetime(2026, 7, 2).date())
        self.assertEqual(summary["days"][0]["hm"], "8h 0m")

    @override_settings(TIME_ZONE="Asia/Kolkata", USE_TZ=True, AUTO_LOGOUT_IDLE_SECONDS=3 * 60 * 60)
    def test_attendance_counts_auto_timeout_after_excluding_idle_window(self):
        user = make_user(username="auto-attendance-user")
        kolkata = ZoneInfo("Asia/Kolkata")
        login_at = timezone.make_aware(datetime(2026, 7, 5, 9), kolkata)
        logout_at = timezone.make_aware(datetime(2026, 7, 5, 20), kolkata)
        UserLoginSession.objects.create(
            user=user,
            session_key="auto-attendance",
            login_at=login_at,
            logout_at=logout_at,
            end_reason=UserSessionEndReason.AUTO_TIMEOUT,
        )

        summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user=user),
            datetime(2026, 7, 5).date(),
            datetime(2026, 7, 5).date(),
        )

        self.assertEqual(summary["attendance_days"], 1)
        self.assertEqual(summary["days"][0]["hm"], "8h 0m")

    @override_settings(TIME_ZONE="Asia/Kolkata", USE_TZ=True)
    def test_attendance_splits_login_time_across_calendar_days(self):
        user = make_user(username="overnight-attendance-user")
        kolkata = ZoneInfo("Asia/Kolkata")

        def aware(day, hour):
            return timezone.make_aware(datetime(2026, 7, day, hour), kolkata)

        UserLoginSession.objects.create(
            user=user,
            session_key="overnight-session",
            login_at=aware(6, 20),
            logout_at=aware(7, 6),
            end_reason=UserSessionEndReason.LOGOUT,
        )
        UserLoginSession.objects.create(
            user=user,
            session_key="morning-session",
            login_at=aware(7, 7),
            logout_at=aware(7, 9),
            end_reason=UserSessionEndReason.LOGOUT,
        )

        summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user=user),
            datetime(2026, 7, 6).date(),
            datetime(2026, 7, 7).date(),
        )

        self.assertEqual(summary["attendance_days"], 1)
        self.assertEqual(summary["days"][0]["date"], datetime(2026, 7, 7).date())
        self.assertEqual(summary["days"][0]["hm"], "8h 0m")

    def test_hm_formatter_uses_sixty_minutes_per_hour(self):
        self.assertEqual(_format_seconds_hm(100 * 60), "1h 40m")

    @override_settings(TIME_ZONE="Asia/Kolkata", USE_TZ=True, AUTO_LOGOUT_IDLE_SECONDS=3 * 60 * 60)
    def test_auto_timeout_reports_used_time_after_idle_window(self):
        user = make_user(username="auto-timeout-report-user")
        kolkata = ZoneInfo("Asia/Kolkata")
        login_at = timezone.make_aware(datetime(2026, 7, 4, 9), kolkata)
        logout_at = timezone.make_aware(datetime(2026, 7, 4, 18), kolkata)
        UserLoginSession.objects.create(
            user=user,
            session_key="auto-timeout-nine-hours",
            login_at=login_at,
            logout_at=logout_at,
            end_reason=UserSessionEndReason.AUTO_TIMEOUT,
        )

        table = _build_login_month_table(
            UserLoginSession.objects.filter(user=user),
            work_sessions_qs=WorkSession.objects.none(),
            date_from=datetime(2026, 7, 4).date(),
            date_to=datetime(2026, 7, 4).date(),
        )

        self.assertEqual(table["rows"][0]["logged_hm"], "6h 0m")
        self.assertEqual(table["rows"][0]["idle_hm"], "3h 0m")
        self.assertEqual(table["total_login_hm"], "6h 0m")

    def test_work_total_includes_live_active_task_time(self):
        user = make_user(username="live-task-worker")
        project = Project.objects.create(name="Live Work Project")
        task = Task.objects.create(
            project=project,
            name="Live Work Task",
            status=TaskStatus.IN_PROGRESS,
        )
        now = timezone.now()
        session = WorkSession.objects.create(
            user=user,
            project=project,
            task=task,
            started_at=now - timedelta(hours=1),
            last_resumed_at=now - timedelta(minutes=30),
            work_seconds=30 * 60,
        )

        with patch("django.utils.timezone.now", return_value=now):
            total_seconds = _sum_work_session_seconds([session])

        self.assertEqual(total_seconds, 60 * 60)

    @override_settings(TIME_ZONE="Asia/Kolkata", USE_TZ=True)
    def test_expired_checkout_counts_only_after_manager_approval(self):
        user = make_user(username="missing-checkout-user")
        kolkata = ZoneInfo("Asia/Kolkata")
        login_at = timezone.make_aware(datetime(2026, 7, 8, 9), kolkata)
        session = UserLoginSession.objects.create(
            user=user,
            session_key="missing-checkout",
            login_at=login_at,
            expires_at=login_at + timedelta(hours=16),
            logout_at=login_at + timedelta(hours=16),
            end_reason=UserSessionEndReason.SESSION_EXPIRED,
            checkout_review_status=CheckoutReviewStatus.PENDING,
            requested_logout_at=login_at + timedelta(hours=9),
        )

        pending_summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user=user),
            login_at.date(),
            login_at.date(),
        )
        self.assertEqual(pending_summary["attendance_days"], 0)

        session.checkout_review_status = CheckoutReviewStatus.APPROVED
        session.save(update_fields=["checkout_review_status"])
        approved_summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user=user),
            login_at.date(),
            login_at.date(),
        )
        self.assertEqual(approved_summary["attendance_days"], 1)


class ReportRoleVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_group = Group.objects.get(name=ROLE_ADMIN)
        cls.crm_group = Group.objects.get(name=ROLE_CRM_MANAGER)
        cls.manager_group = Group.objects.get(name=ROLE_PROJECT_MANAGER)
        cls.employee_group = Group.objects.get(name=ROLE_EMPLOYEE)

        cls.admin = make_user(username="report-admin")
        cls.admin.groups.add(cls.admin_group)
        cls.crm_manager = make_user(username="report-crm-manager")
        cls.crm_manager.groups.add(cls.crm_group)
        cls.project_manager = make_user(username="report-project-manager")
        cls.project_manager.groups.add(cls.manager_group)
        cls.employee = make_user(username="report-employee")
        cls.employee.groups.add(cls.employee_group)

        cls.project = Project.objects.create(
            name="Restricted Report Project",
            manager=cls.project_manager,
        )
        cls.task = Task.objects.create(
            project=cls.project,
            name="ADMIN-ONLY-TASK-DETAIL",
            assigned_to=cls.employee,
            status=TaskStatus.PAUSED,
            due_date=timezone.localdate() - timedelta(days=1),
        )
        WorkSession.objects.create(
            user=cls.employee,
            project=cls.project,
            task=cls.task,
            status=WorkSessionStatus.PAUSED,
            work_seconds=60 * 60,
        )

    def test_employee_cannot_access_reports_or_see_sidebar_link(self):
        self.client.force_login(self.employee)

        report_response = self.client.get(reverse("reports:dashboard"))
        home_response = self.client.get(reverse("ui:home"))

        self.assertEqual(report_response.status_code, 403)
        self.assertNotContains(
            home_response,
            f'href="{reverse("reports:dashboard")}"',
            html=False,
        )
        self.assertContains(home_response, reverse("reports:attendance"))

    def test_managers_receive_kpis_without_detailed_rows(self):
        self.client.force_login(self.project_manager)
        project_response = self.client.get(reverse("reports:project_report"))
        employee_response = self.client.get(
            reverse("reports:employee_work_report"),
            {"user": self.employee.pk},
        )

        self.assertEqual(project_response.status_code, 200)
        self.assertFalse(project_response.context["show_detailed_data"])
        self.assertNotContains(project_response, "ADMIN-ONLY-TASK-DETAIL")
        self.assertEqual(employee_response.status_code, 200)
        self.assertFalse(employee_response.context["show_detailed_data"])
        self.assertNotContains(employee_response, "ADMIN-ONLY-TASK-DETAIL")
        self.assertEqual(employee_response.context["login_table"]["rows"], [])

        self.client.force_login(self.crm_manager)
        sales_response = self.client.get(reverse("reports:sales_report"))
        self.assertEqual(sales_response.status_code, 200)
        self.assertFalse(sales_response.context["show_detailed_data"])

    def test_admin_can_see_task_and_login_work_details(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("reports:employee_work_report"),
            {"user": self.employee.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_detailed_data"])
        self.assertContains(response, "ADMIN-ONLY-TASK-DETAIL")
        self.assertContains(response, "Login Sessions")

    def test_project_manager_can_approve_managed_employee_checkout(self):
        login_at = timezone.now() - timedelta(hours=10)
        session = UserLoginSession.objects.create(
            user=self.employee,
            session_key="manager-review-checkout",
            login_at=login_at,
            expires_at=login_at + timedelta(hours=16),
            logout_at=login_at + timedelta(hours=16),
            end_reason=UserSessionEndReason.SESSION_EXPIRED,
            checkout_review_status=CheckoutReviewStatus.PENDING,
            requested_logout_at=login_at + timedelta(hours=9),
            checkout_request_note="Browser was closed accidentally.",
        )
        self.client.force_login(self.project_manager)

        response = self.client.post(
            reverse("reports:attendance"),
            {
                "action": "approve_checkout",
                "session_id": session.pk,
                "review_note": "Confirmed with the team lead.",
            },
        )

        self.assertRedirects(response, reverse("reports:attendance"))
        session.refresh_from_db()
        self.assertEqual(session.checkout_review_status, CheckoutReviewStatus.APPROVED)
        self.assertEqual(session.reviewed_by, self.project_manager)

    def test_submitted_checkout_hides_form_and_shows_manager_request_message(self):
        login_at = timezone.now() - timedelta(hours=12)
        session = UserLoginSession.objects.create(
            user=self.employee,
            session_key="employee-correction",
            login_at=login_at,
            expires_at=login_at + timedelta(hours=16),
            logout_at=login_at + timedelta(hours=16),
            end_reason=UserSessionEndReason.SESSION_EXPIRED,
            checkout_review_status=CheckoutReviewStatus.PENDING,
        )
        requested_logout = timezone.localtime(login_at + timedelta(hours=9))
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("reports:attendance"),
            {
                "action": "submit_checkout",
                "session_id": session.pk,
                "requested_logout_at": requested_logout.strftime("%Y-%m-%dT%H:%M"),
                "checkout_request_note": "Internet connection failed before checkout.",
            },
            follow=True,
        )

        self.assertContains(response, "Correction sent - waiting for manager review")
        self.assertNotContains(
            response,
            f'name="session_id" value="{session.pk}"',
            html=False,
        )

        self.client.force_login(self.project_manager)
        manager_response = self.client.get(reverse("reports:attendance"))
        self.assertContains(manager_response, "Employee correction request")
        self.assertContains(manager_response, "Internet connection failed before checkout.")
        self.assertContains(manager_response, "approve_checkout")
        self.assertContains(manager_response, "reject_checkout")

    def test_rejected_checkout_can_be_corrected_and_resubmitted(self):
        login_at = timezone.now() - timedelta(hours=12)
        session = UserLoginSession.objects.create(
            user=self.employee,
            session_key="rejected-correction",
            login_at=login_at,
            expires_at=login_at + timedelta(hours=16),
            logout_at=login_at + timedelta(hours=16),
            end_reason=UserSessionEndReason.SESSION_EXPIRED,
            checkout_review_status=CheckoutReviewStatus.PENDING,
            requested_logout_at=login_at + timedelta(hours=10),
            checkout_request_note="First request",
        )
        self.client.force_login(self.project_manager)
        self.client.post(
            reverse("reports:attendance"),
            {
                "action": "reject_checkout",
                "session_id": session.pk,
                "review_note": "Please enter the actual earlier checkout time.",
            },
        )
        session.refresh_from_db()
        self.assertEqual(session.checkout_review_status, CheckoutReviewStatus.REJECTED)

        self.client.force_login(self.employee)
        employee_response = self.client.get(reverse("reports:attendance"))
        self.assertContains(employee_response, "Update the correction and submit it again.")
        self.assertContains(
            employee_response,
            f'name="session_id" value="{session.pk}"',
            html=False,
        )

        corrected_logout = timezone.localtime(login_at + timedelta(hours=9))
        self.client.post(
            reverse("reports:attendance"),
            {
                "action": "submit_checkout",
                "session_id": session.pk,
                "requested_logout_at": corrected_logout.strftime("%Y-%m-%dT%H:%M"),
                "checkout_request_note": "Corrected checkout time.",
            },
        )
        session.refresh_from_db()
        self.assertEqual(session.checkout_review_status, CheckoutReviewStatus.PENDING)
        self.assertEqual(session.checkout_request_note, "Corrected checkout time.")
        self.assertIsNone(session.reviewed_by)
        self.assertIsNone(session.reviewed_at)
        self.assertEqual(session.review_note, "")

    def test_employee_submits_leave_and_manager_approves_it(self):
        self.client.force_login(self.employee)
        start_date = timezone.localdate() + timedelta(days=2)
        response = self.client.post(
            reverse("reports:attendance"),
            {
                "action": "submit_leave",
                "leave_type": "casual",
                "start_date": start_date.isoformat(),
                "end_date": (start_date + timedelta(days=1)).isoformat(),
                "reason": "Family appointment",
            },
        )
        self.assertRedirects(response, reverse("reports:attendance"))
        leave = LeaveRequest.objects.get(user=self.employee)
        self.assertEqual(leave.status, LeaveStatus.PENDING)

        self.client.force_login(self.project_manager)
        response = self.client.post(
            reverse("reports:attendance"),
            {
                "action": "approve_leave",
                "leave_id": leave.pk,
                "review_note": "Approved for the requested dates.",
            },
        )
        self.assertRedirects(response, reverse("reports:attendance"))
        leave.refresh_from_db()
        self.assertEqual(leave.status, LeaveStatus.APPROVED)
        self.assertEqual(leave.reviewed_by, self.project_manager)
