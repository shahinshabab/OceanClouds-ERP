from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.models import (
    CheckoutReviewStatus,
    UserLoginSession,
    UserSessionEndReason,
)
from projects.utils import pause_active_work_sessions_for_user


def session_lifetime():
    seconds = int(getattr(settings, "LOGIN_SESSION_MAX_SECONDS", 12 * 60 * 60))
    return timedelta(seconds=seconds)


def idle_timeout():
    """None when idle logout is turned off."""
    seconds = int(getattr(settings, "LOGIN_IDLE_TIMEOUT_SECONDS", 0) or 0)
    return timedelta(seconds=seconds) if seconds > 0 else None


def idle_cutoff(now=None):
    """Logins whose last activity is at or before this time are idle."""
    timeout = idle_timeout()
    if timeout is None:
        return None
    return (now or timezone.now()) - timeout


def _end_of(login_session, cutoff):
    """
    Which limit a login reached first: (reason, logout_at, review_status).

    Idle logins end at their last activity, which is real used time and needs
    no review. Logins active through the fixed deadline end at that deadline
    and need a reviewed checkout, as before.
    """
    timeout = idle_timeout()
    idle_deadline = (
        login_session.last_activity_at + timeout if timeout is not None else None
    )
    if (
        cutoff is not None
        and login_session.last_activity_at <= cutoff
        and (
            login_session.expires_at is None
            or idle_deadline <= login_session.expires_at
        )
    ):
        logout_at = max(login_session.last_activity_at, login_session.login_at)
        return (
            UserSessionEndReason.IDLE_TIMEOUT,
            logout_at,
            CheckoutReviewStatus.NOT_REQUIRED,
        )
    return (
        UserSessionEndReason.SESSION_EXPIRED,
        login_session.expires_at,
        CheckoutReviewStatus.PENDING,
    )


def close_expired_login_sessions(now=None):
    """
    Close logins that went idle or reached their fixed deadline, end their
    browser sessions and sockets, and pause active work when they ended.
    """
    from common.live import end_session_sockets

    now = now or timezone.now()
    cutoff = idle_cutoff(now)
    ended = Q(expires_at__lte=now)
    if cutoff is not None:
        ended |= Q(last_activity_at__lte=cutoff)

    closed_sessions = []

    with transaction.atomic():
        candidates = list(
            UserLoginSession.objects.select_for_update()
            .filter(logout_at__isnull=True)
            .filter(ended)
        )

        for login_session in candidates:
            reason, logout_at, review_status = _end_of(login_session, cutoff)
            login_session.logout_at = logout_at
            login_session.end_reason = reason
            login_session.checkout_review_status = review_status
            login_session.save(
                update_fields=[
                    "logout_at",
                    "end_reason",
                    "checkout_review_status",
                ]
            )
            closed_sessions.append(login_session)

        for login_session in closed_sessions:
            end_session_sockets(
                login_session.user_id,
                login_session.session_key,
                login_session.end_reason,
            )

    closed_session_keys = [login_session.session_key for login_session in closed_sessions]
    if closed_session_keys:
        Session.objects.filter(session_key__in=closed_session_keys).delete()

    from reports.notifications import notify_missing_logout

    for login_session in closed_sessions:
        if login_session.checkout_review_status == CheckoutReviewStatus.PENDING:
            notify_missing_logout(login_session)

    for login_session in closed_sessions:
        if not UserLoginSession.objects.filter(
            user_id=login_session.user_id,
            logout_at__isnull=True,
        ).exists():
            pause_active_work_sessions_for_user(
                login_session.user_id,
                paused_at=login_session.logout_at,
            )

    return closed_session_keys
