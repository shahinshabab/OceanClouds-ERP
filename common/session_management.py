from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from common.models import (
    CheckoutReviewStatus,
    UserLoginSession,
    UserSessionEndReason,
)
from projects.utils import pause_active_work_sessions_for_user


def session_lifetime():
    seconds = int(getattr(settings, "LOGIN_SESSION_MAX_SECONDS", 16 * 60 * 60))
    return timedelta(seconds=seconds)


def close_expired_login_sessions(now=None):
    """Close every absolute-expiry login and pause active work at its deadline."""
    now = now or timezone.now()
    closed_session_keys = []

    with transaction.atomic():
        expired_sessions = list(
            UserLoginSession.objects.select_for_update()
            .filter(logout_at__isnull=True, expires_at__lte=now)
            .select_related("user")
        )

        for login_session in expired_sessions:
            login_session.logout_at = login_session.expires_at
            login_session.end_reason = UserSessionEndReason.SESSION_EXPIRED
            login_session.checkout_review_status = CheckoutReviewStatus.PENDING
            login_session.save(
                update_fields=[
                    "logout_at",
                    "end_reason",
                    "checkout_review_status",
                ]
            )
            closed_session_keys.append(login_session.session_key)

    if closed_session_keys:
        Session.objects.filter(session_key__in=closed_session_keys).delete()

    for login_session in expired_sessions:
        if not UserLoginSession.objects.filter(
            user_id=login_session.user_id,
            logout_at__isnull=True,
        ).exists():
            pause_active_work_sessions_for_user(
                login_session.user_id,
                paused_at=login_session.expires_at,
            )

    return closed_session_keys
