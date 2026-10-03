# common/signals.py

from datetime import timedelta

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone

from .models import CheckoutReviewStatus, UserLoginSession, UserSessionEndReason


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
@transaction.atomic
def record_user_login(sender, request, user, **kwargs):
    if not request.session.session_key:
        request.session.save()

    session_key = request.session.session_key
    now = timezone.now()

    replaced_session_keys = list(
        UserLoginSession.objects.select_for_update()
        .filter(user=user, logout_at__isnull=True)
        .exclude(session_key=session_key)
        .values_list("session_key", flat=True)
    )
    if replaced_session_keys:
        UserLoginSession.objects.filter(
            user=user,
            session_key__in=replaced_session_keys,
            logout_at__isnull=True,
        ).update(
            logout_at=now,
            end_reason=UserSessionEndReason.SESSION_REPLACED,
            checkout_review_status=CheckoutReviewStatus.PENDING,
        )
        Session.objects.filter(session_key__in=replaced_session_keys).delete()

    active_session = UserLoginSession.objects.filter(
        user=user,
        session_key=session_key,
        logout_at__isnull=True,
    ).first()

    if active_session:
        active_session.ip_address = get_client_ip(request)
        active_session.user_agent = request.META.get("HTTP_USER_AGENT", "")
        active_session.last_activity_at = now
        active_session.expires_at = active_session.login_at + timedelta(
            seconds=int(getattr(settings, "LOGIN_SESSION_MAX_SECONDS", 16 * 60 * 60))
        )
        active_session.save(
            update_fields=["ip_address", "user_agent", "last_activity_at", "expires_at"]
        )
        return

    UserLoginSession.objects.create(
        user=user,
        session_key=session_key,
        login_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(
            seconds=int(getattr(settings, "LOGIN_SESSION_MAX_SECONDS", 16 * 60 * 60))
        ),
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


@receiver(user_logged_out)
def record_user_logout(sender, request, user, **kwargs):
    if not user or not request:
        return

    from projects.utils import pause_active_work_sessions_for_user

    session_key = request.session.session_key

    UserLoginSession.objects.filter(
        user=user,
        session_key=session_key,
        logout_at__isnull=True,
    ).update(
        logout_at=timezone.now(),
        end_reason=UserSessionEndReason.LOGOUT,
    )

    pause_active_work_sessions_for_user(user)
