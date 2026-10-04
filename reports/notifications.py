# reports/notifications.py
"""
Missing logout notices.

A login left open until the fixed limit closes without a logout time. The
user is told to request their real logout time; the request goes to the
project managers who look after them (admins when there are none), and the
user hears back when it is approved or rejected.
"""

from django.contrib.auth import get_user_model
from django.utils import timezone

from common.models import Notification
from common.notifications import notify_user
from common.roles import ROLE_ADMIN, ROLE_PROJECT_MANAGER

from .utils import _employee_options_for_user


def checkout_reviewers(employee):
    users = get_user_model().objects.filter(is_active=True).exclude(pk=employee.pk)
    managers = [
        manager
        for manager in users.filter(groups__name=ROLE_PROJECT_MANAGER).distinct()
        if manager.has_perm("common.review_attendance")
        and _employee_options_for_user(manager).filter(pk=employee.pk).exists()
    ]
    if managers:
        return managers
    return list(users.filter(groups__name=ROLE_ADMIN).distinct()) or list(users.filter(is_superuser=True))


def _login_label(login_session):
    return timezone.localtime(login_session.login_at).strftime("%d %b, %I:%M %p")


def notify_missing_logout(login_session):
    notify_user(
        recipient=login_session.user,
        notif_type=Notification.Type.ATTENDANCE_CHECKOUT,
        target=login_session,
        message=f"No logout for your login on {_login_label(login_session)}. "
                "Request your logout time on the attendance page.",
        extra_key="missing",
    )


def notify_checkout_requested(login_session):
    name = login_session.user.get_full_name() or login_session.user.username
    for reviewer in checkout_reviewers(login_session.user):
        notify_user(
            recipient=reviewer,
            actor=login_session.user,
            notif_type=Notification.Type.ATTENDANCE_CHECKOUT,
            target=login_session,
            message=f"{name} asks to fix a missing logout ({_login_label(login_session)}).",
            extra_key=f"request:{timezone.now().isoformat()}",
        )


def notify_checkout_reviewed(login_session):
    notify_user(
        recipient=login_session.user,
        actor=login_session.reviewed_by,
        notif_type=Notification.Type.ATTENDANCE_CHECKOUT,
        target=login_session,
        message=f"Your logout time for {_login_label(login_session)} was "
                f"{login_session.get_checkout_review_status_display().lower()}.",
        extra_key=f"review:{timezone.now().isoformat()}",
    )
