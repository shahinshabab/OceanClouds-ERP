from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from common.models import UserLoginSession
from common.test_helpers import AuthenticatedViewTestMixin, make_user

from .forms import ProfileUpdateForm


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
