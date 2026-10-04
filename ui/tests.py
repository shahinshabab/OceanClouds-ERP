from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse

from common.models import ImportantNotice, UserLoginSession
from common.test_helpers import AuthenticatedViewTestMixin, make_user
from projects.models import Project, Task, TaskStatus, WorkSession, WorkSessionStatus

from .forms import ProfileUpdateForm


class LogoutTrackingTests(TestCase):
    def setUp(self):
        self.user = make_user(username="logout-user", password="secret12345")
        self.client.post(
            reverse("ui:login"),
            {"username": self.user.username, "password": "secret12345"},
        )
        self.login_session = UserLoginSession.objects.get(user=self.user)
        self.project = Project.objects.create(name="Logout project")
        self.task = Task.objects.create(
            project=self.project,
            name="Logout task",
            status=TaskStatus.IN_PROGRESS,
        )
        self.work_session = WorkSession.objects.create(
            user=self.user,
            project=self.project,
            task=self.task,
        )

    def assert_logout_recorded(self):
        response = self.client.get(reverse("ui:logout"))

        self.assertRedirects(response, reverse("ui:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.login_session.refresh_from_db()
        self.work_session.refresh_from_db()
        self.task.refresh_from_db()
        self.assertIsNotNone(self.login_session.logout_at)
        self.assertEqual(self.login_session.end_reason, "logout")
        self.assertEqual(self.login_session.checkout_review_status, "not_required")
        self.assertFalse(
            UserLoginSession.objects.filter(user=self.user, logout_at__isnull=True).exists()
        )
        self.assertEqual(self.work_session.status, WorkSessionStatus.PAUSED)
        self.assertEqual(self.task.status, TaskStatus.PAUSED)
        protected_response = self.client.get(reverse("ui:home"))
        self.assertEqual(protected_response.status_code, 302)
        self.assertIn(reverse("ui:login"), protected_response["Location"])

    def test_manual_logout_records_checkout_and_pauses_work(self):
        self.assert_logout_recorded()

    def test_required_notice_does_not_block_logout(self):
        ImportantNotice.objects.create(
            key="logout-policy", title="Required policy", body="Please agree."
        )

        self.assert_logout_recorded()

    def test_logout_after_password_change_records_checkout(self):
        self.change_password_and_logout("ui:profile_password", "ui:profile")

    def test_logout_after_admin_password_change_records_checkout(self):
        self.change_password_and_logout("admin:password_change", "admin:password_change_done")

    def change_password_and_logout(self, password_url_name, success_url_name):
        original_key = self.login_session.session_key
        original_login_at = self.login_session.login_at
        original_expires_at = self.login_session.expires_at
        response = self.client.post(
            reverse(password_url_name),
            {
                "old_password": "secret12345",
                "new_password1": "changed-secret12345",
                "new_password2": "changed-secret12345",
            },
        )

        self.assertRedirects(response, reverse(success_url_name))
        self.assertNotEqual(original_key, self.client.session.session_key)
        rotated_key = self.client.session.session_key
        self.assert_logout_recorded()
        self.assertEqual(self.login_session.session_key, rotated_key)
        self.assertEqual(self.login_session.login_at, original_login_at)
        self.assertEqual(self.login_session.expires_at, original_expires_at)
        self.assertEqual(UserLoginSession.objects.filter(user=self.user).count(), 1)

    def test_logout_from_replaced_browser_keeps_current_login_and_work_active(self):
        current_browser = Client()
        current_browser.post(
            reverse("ui:login"),
            {"username": self.user.username, "password": "secret12345"},
        )
        current_login = UserLoginSession.objects.get(user=self.user, logout_at__isnull=True)

        response = self.client.get(reverse("ui:logout"))

        self.assertRedirects(response, reverse("ui:login"))
        current_login.refresh_from_db()
        self.work_session.refresh_from_db()
        self.assertIsNone(current_login.logout_at)
        self.assertEqual(self.work_session.status, WorkSessionStatus.ACTIVE)
        self.assertEqual(current_browser.get(reverse("ui:home")).status_code, 200)


class UiTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "ui:home",
        "ui:profile",
        "ui:profile_edit",
        "ui:profile_password",
    ]

    def test_login_page_loads(self):
        response = self.client.get(reverse("ui:login"))

        self.assertEqual(response.status_code, 200)

    def test_authenticated_layout_includes_refined_sidebar(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("ui:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sidebarNavigation"')
        self.assertContains(response, 'id="sidebarSearch"')
        self.assertContains(response, 'class="sidebar-brand-mark"')
        self.assertNotContains(response, "View profile")
        self.assertNotContains(response, 'class="sidebar-user"')
        self.assertContains(response, "height: 100dvh;")
        self.assertContains(response, "min-height: 0;")

    def test_profile_page_renders_account_overview(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("ui:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="profileName"')
        self.assertContains(response, "Personal information")
        self.assertContains(response, "Assigned roles")
        self.assertContains(response, "Last successful login")
        self.assertContains(response, reverse("ui:profile_edit"))
        self.assertContains(response, reverse("ui:profile_password"))

    def test_login_with_valid_credentials_redirects_home(self):
        user = make_user(username="login-user", password="secret12345")

        response = self.client.post(
            reverse("ui:login"),
            data={"username": user.username, "password": "secret12345"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("ui:home"))

    def test_repeated_login_in_same_browser_keeps_one_active_session(self):
        user = make_user(username="repeat-login-user", password="secret12345")
        login_data = {"username": user.username, "password": "secret12345"}

        self.client.post(
            reverse("ui:login"),
            data=login_data,
            REMOTE_ADDR="192.0.2.10",
        )
        self.client.post(
            reverse("ui:login"),
            data=login_data,
            REMOTE_ADDR="192.0.2.11",
        )

        sessions = UserLoginSession.objects.filter(
            user=user,
            logout_at__isnull=True,
        )
        self.assertEqual(sessions.count(), 1)
        self.assertEqual(sessions.get().ip_address, "192.0.2.11")

    def test_new_login_invalidates_users_previous_browser_session(self):
        user = make_user(username="single-session-user", password="secret12345")
        login_data = {"username": user.username, "password": "secret12345"}
        first_browser = Client()
        second_browser = Client()

        first_browser.post(reverse("ui:login"), data=login_data)
        first_session_key = first_browser.session.session_key

        second_browser.post(reverse("ui:login"), data=login_data)

        self.assertFalse(Session.objects.filter(session_key=first_session_key).exists())
        self.assertEqual(
            UserLoginSession.objects.filter(
                user=user,
                logout_at__isnull=True,
            ).count(),
            1,
        )
        self.assertTrue(
            UserLoginSession.objects.filter(
                user=user,
                session_key=first_session_key,
                end_reason="session_replaced",
                logout_at__isnull=False,
            ).exists()
        )

        response = first_browser.get(reverse("ui:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("ui:login"), response["Location"])

    def test_profile_form_updates_user_fields(self):
        form = ProfileUpdateForm(
            data={
                "first_name": "Ocean",
                "last_name": "User",
                "email": "ocean@example.com",
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.email, "ocean@example.com")
