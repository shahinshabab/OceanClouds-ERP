# common/middleware.py

from urllib.parse import urlencode, urlparse

from django.contrib.auth import logout as auth_logout
from django.contrib.messages import get_messages
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from common.models import ImportantNotice, UserLoginSession
from common.session_management import close_expired_login_sessions


class CloseExpiredLoginSessionsMiddleware:
    """
    Enforces the fixed login deadline without treating page inactivity as work
    inactivity. A scheduled command performs the same cleanup between requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        expired_keys = set(close_expired_login_sessions())

        current_session_key = request.session.session_key
        if (
            current_session_key in expired_keys
            and request.user.is_authenticated
        ):
            auth_logout(request)

        response = self.get_response(request)

        if request.user.is_authenticated and request.session.session_key:
            UserLoginSession.objects.filter(
                user_id=request.user.pk,
                session_key=request.session.session_key,
                logout_at__isnull=True,
            ).update(last_activity_at=timezone.now())

        return response


class RequireNoticeAcknowledgementMiddleware:
    """Keep authenticated users on the notice page until required notices are agreed."""

    allowed_prefixes = (
        "/admin/",
        "/static/",
        "/media/",
        "/healthz",
        "/logout/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        notice_url = reverse("common:important_notice")
        if request.path == notice_url or request.path.startswith(self.allowed_prefixes):
            return self.get_response(request)

        now = timezone.now()
        has_pending_notice = (
            ImportantNotice.objects
            .filter(
                is_active=True,
                requires_acknowledgement=True,
                published_at__lte=now,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .exclude(acknowledgements__user=request.user)
            .exists()
        )
        if has_pending_notice:
            response = redirect(notice_url)
            response["Location"] += "?" + urlencode({"next": request.get_full_path()})
            return response

        return self.get_response(request)


class ClearFrontendMessagesBeforeAdminMiddleware:
    """
    Clear pending frontend messages when opening /admin/
    from a non-admin page.

    This prevents app messages like:
    'Event updated successfully'
    from appearing in Django admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_admin_path = request.path.startswith("/admin/")

        referer = request.META.get("HTTP_REFERER", "")
        referer_path = urlparse(referer).path if referer else ""

        came_from_admin = referer_path.startswith("/admin/")

        if is_admin_path and not came_from_admin:
            # Iterating get_messages(request) consumes pending messages.
            list(get_messages(request))

        return self.get_response(request)
