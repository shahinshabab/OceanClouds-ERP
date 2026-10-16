# crm/signals.py

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from common.models import Notification
from common.notifications import notify_user
from todos.models import TodoPriority
from todos.services import create_todo_once
from crm.models import Inquiry


# Follow-up to-do titles; the sales report counts the completed ones.
INQUIRY_FOLLOW_UP_TODO_PREFIX = "Follow up inquiry: "
LEAD_ACTION_TODO_PREFIX = "Lead next action: "


@receiver(pre_save, sender=Inquiry)
def cache_old_inquiry_handler(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return

    if not instance.pk:
        instance._old_handled_by_id = None
        return

    old = sender.objects.filter(pk=instance.pk).only("handled_by").first()
    instance._old_handled_by_id = old.handled_by_id if old else None


@receiver(post_save, sender=Inquiry)
def notify_and_todo_inquiry_assigned(sender, instance, created, **kwargs):
    """
    Inquiry assignment:
    - Notify assigned CRM person instantly.
    - Create todo for assigned CRM person.
    """

    if kwargs.get("raw") or not instance.handled_by_id:
        return

    old_handled_by_id = getattr(instance, "_old_handled_by_id", None)

    if not created and old_handled_by_id == instance.handled_by_id:
        return

    actor = getattr(instance, "owner", None)

    notify_user(
        recipient=instance.handled_by,
        actor=actor,
        notif_type=Notification.Type.INQUIRY_ASSIGNED,
        target=instance,
        message=f"New inquiry assigned for follow-up: {instance}",
    )

    create_todo_once(
        title=f"{INQUIRY_FOLLOW_UP_TODO_PREFIX}{instance}",
        description=(
            "This inquiry has been assigned to you. "
            "Please contact the client and update the inquiry status."
        ),
        owner=actor or instance.handled_by,
        assigned_to=instance.handled_by,
        priority=TodoPriority.HIGH,
        due_date=None,
        client=instance.client,
        lead=instance.lead,
    )
