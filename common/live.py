# common/live.py
"""
Websocket pushes for live updates.

Saves never wait on or fail because of websockets: every push is sent after
the database transaction commits, and channel layer errors are only logged.
Payloads carry ids and short labels; pages refresh themselves to load data
through the normal permission-checked views.
"""

import hashlib
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

GROUP_INQUIRIES = "live.inquiries"
GROUP_ADMINS = "live.admins"


def user_group(user_id):
    return f"live.user.{user_id}"


def session_tag(session_key):
    """Identifies a browser session in payloads without exposing its key."""
    return hashlib.sha256(f"live:{session_key}".encode()).hexdigest()[:32]


def _send_now(groups, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    message = {"type": "live.event", "payload": payload}
    for group in groups:
        try:
            async_to_sync(channel_layer.group_send)(group, message)
        except Exception:
            logger.warning("Live update to %s failed", group, exc_info=True)


def push(groups, payload):
    groups = sorted({group for group in groups if group})
    if groups:
        transaction.on_commit(lambda: _send_now(groups, payload))


def _user_groups(*user_ids):
    return [user_group(user_id) for user_id in user_ids if user_id]


def _action(created=None, deleted=False):
    if deleted:
        return "deleted"
    return "created" if created else "updated"


# ----------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------


@receiver(post_save, sender="common.Notification", dispatch_uid="live_notification")
def push_notification(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return

    # Read/unread changes also refresh the bell in the user's other tabs.
    push(
        _user_groups(instance.recipient_id),
        {
            "kind": "notification",
            "action": _action(created),
            "id": instance.pk,
            "message": instance.message or instance.get_notif_type_display(),
        },
    )


# ----------------------------------------------------------------------
# Inquiries (visible to every inquiry role)
# ----------------------------------------------------------------------


def _push_inquiry(instance, action):
    label = instance.name or instance.phone or instance.email or f"#{instance.pk}"
    push(
        [GROUP_INQUIRIES],
        {
            "kind": "inquiry",
            "action": action,
            "id": instance.pk,
            "label": label,
            "channel": instance.get_channel_display(),
        },
    )


@receiver(post_save, sender="crm.Inquiry", dispatch_uid="live_inquiry_saved")
def push_inquiry_saved(sender, instance, created, **kwargs):
    if not kwargs.get("raw"):
        _push_inquiry(instance, _action(created))


@receiver(post_delete, sender="crm.Inquiry", dispatch_uid="live_inquiry_deleted")
def push_inquiry_deleted(sender, instance, **kwargs):
    _push_inquiry(instance, _action(deleted=True))


# ----------------------------------------------------------------------
# Project tasks (admins, the project manager, old and new assignee)
# ----------------------------------------------------------------------


@receiver(pre_save, sender="projects.Task", dispatch_uid="live_task_old_assignee")
def remember_task_assignee(sender, instance, **kwargs):
    if kwargs.get("raw") or not instance.pk:
        return
    instance._live_old_assigned_to_id = (
        sender.objects.filter(pk=instance.pk)
        .values_list("assigned_to_id", flat=True)
        .first()
    )


def _push_task(instance, action):
    manager_id = (
        type(instance.project).objects.filter(pk=instance.project_id)
        .values_list("manager_id", flat=True)
        .first()
    )
    push(
        [GROUP_ADMINS]
        + _user_groups(
            manager_id,
            instance.assigned_to_id,
            getattr(instance, "_live_old_assigned_to_id", None),
        ),
        {
            "kind": "task",
            "action": action,
            "id": instance.pk,
            "project_id": instance.project_id,
            "label": instance.name,
        },
    )


@receiver(post_save, sender="projects.Task", dispatch_uid="live_task_saved")
def push_task_saved(sender, instance, created, **kwargs):
    if not kwargs.get("raw"):
        _push_task(instance, _action(created))


@receiver(post_delete, sender="projects.Task", dispatch_uid="live_task_deleted")
def push_task_deleted(sender, instance, **kwargs):
    _push_task(instance, _action(deleted=True))


# ----------------------------------------------------------------------
# To-dos (admins, owner, old and new assignee, linked project managers)
# ----------------------------------------------------------------------


@receiver(pre_save, sender="todos.Todo", dispatch_uid="live_todo_old_assignee")
def remember_todo_assignee(sender, instance, **kwargs):
    if kwargs.get("raw") or not instance.pk:
        return
    instance._live_old_assigned_to_id = (
        sender.objects.filter(pk=instance.pk)
        .values_list("assigned_to_id", flat=True)
        .first()
    )


def _todo_manager_ids(instance):
    from projects.models import Project

    project_ids = set()
    if instance.project_id:
        project_ids.add(instance.project_id)
    if instance.task_id:
        project_ids.add(instance.task.project_id)
    if instance.deliverable_id:
        project_ids.add(instance.deliverable.project_id)
    if not project_ids:
        return []
    return list(
        Project.objects.filter(pk__in=project_ids).values_list("manager_id", flat=True)
    )


def _push_todo(instance, action):
    push(
        [GROUP_ADMINS]
        + _user_groups(
            instance.owner_id,
            instance.assigned_to_id,
            getattr(instance, "_live_old_assigned_to_id", None),
            *_todo_manager_ids(instance),
        ),
        {
            "kind": "todo",
            "action": action,
            "id": instance.pk,
            "label": instance.title,
        },
    )


@receiver(post_save, sender="todos.Todo", dispatch_uid="live_todo_saved")
def push_todo_saved(sender, instance, created, **kwargs):
    if not kwargs.get("raw"):
        _push_todo(instance, _action(created))


@receiver(post_delete, sender="todos.Todo", dispatch_uid="live_todo_deleted")
def push_todo_deleted(sender, instance, **kwargs):
    _push_todo(instance, _action(deleted=True))


# ----------------------------------------------------------------------
# Logout, or a newer login that replaces this one, closes the socket
# ----------------------------------------------------------------------


@receiver(user_logged_out, dispatch_uid="live_logout")
def close_socket_on_logout(sender, request, user, **kwargs):
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if user and session_key:
        _send_now(
            [user_group(user.pk)],
            {"kind": "session_ended", "session": session_tag(session_key)},
        )


@receiver(user_logged_in, dispatch_uid="live_login")
def close_replaced_sockets_on_login(sender, request, user, **kwargs):
    # A new login closes the user's other logins (common.signals), so their
    # sockets must stop receiving this user's updates too.
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if user and session_key:
        _send_now(
            [user_group(user.pk)],
            {"kind": "session_replaced", "keep": session_tag(session_key)},
        )
