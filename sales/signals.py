from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from common.roles import ROLE_ADMIN
from todos.models import TodoPriority
from todos.services import create_todo_once

from .models import Deal, Payment, PaymentType


User = get_user_model()


def get_admin_users():
    return (
        User.objects.filter(
            is_active=True,
            groups__name=ROLE_ADMIN,
        ).distinct()
    )


@receiver(post_save, sender=Payment)
def create_contract_todo_when_advance_payment_received(sender, instance, created, **kwargs):
    """
    Advance payment received:
    - The sales owner sends the contract, then creates the client and event
      once it is signed.
    - Projects are no longer requested here: Project Managers get their
      "create project" to-do when the event is created.
    """

    if kwargs.get("raw") or not created:
        return

    if instance.payment_type != PaymentType.ADVANCE:
        return

    invoice = instance.invoice
    deal = invoice.deal if invoice else None
    contract = invoice.contract if invoice else None
    today = timezone.localdate()

    recipients = [deal.owner] if deal and deal.owner_id else list(get_admin_users())

    for recipient in recipients:
        create_todo_once(
            title=f"Send contract and create event: {deal or invoice}",
            description=(
                "Advance payment has been received. "
                "Send the contract for signing. Once it is signed and invoiced, "
                "use Create Client & Event so the Project Managers can plan the project."
            ),
            owner=recipient,
            assigned_to=recipient,
            priority=TodoPriority.HIGH,
            due_date=today,
            deal=deal,
            contract=contract,
            invoice=invoice,
        )


# ------------------------------------------------------------------
# Deal reminders: a to-do for the expected closing date and one for the
# next action, kept in step with the deal. The daily job
# (generate_due_todos) adds the notification on the day.
# ------------------------------------------------------------------

DEAL_CLOSE_TODO_PREFIX = "Close deal: "
DEAL_ACTION_TODO_PREFIX = "Deal next action: "


def _open_deal_todos(deal, prefix):
    from todos.models import Todo, TodoStatus

    return Todo.objects.filter(
        deal=deal,
        title__startswith=prefix,
        status__in=[TodoStatus.PENDING, TodoStatus.IN_PROGRESS],
    )


def _deal_recipient(deal):
    if deal.owner_id:
        return deal.owner
    if deal.lead_id and deal.lead.owner_id:
        return deal.lead.owner
    return None


def _keep_deal_todo(deal, prefix, title, description, due_date, recipient):
    todos = _open_deal_todos(deal, prefix)
    if not due_date or not deal.is_open or not recipient:
        for todo in todos:
            todo.mark_completed()
        return None

    todo = todos.first()
    if todo:
        wanted = {"title": title, "description": description, "due_date": due_date, "assigned_to": recipient}
        changed = [field for field, value in wanted.items() if getattr(todo, field) != value]
        for field in changed:
            setattr(todo, field, wanted[field])
        if changed:
            todo.save(update_fields=changed + ["updated_at"])
        # Any extra open copies are left over from older edits.
        for extra in todos.exclude(pk=todo.pk):
            extra.mark_completed()
        return todo

    # Already finished for this date: saving the deal again does not bring it back.
    from todos.models import Todo
    if Todo.objects.filter(deal=deal, title=title, due_date=due_date).exists():
        return None

    todo, _ = create_todo_once(
        title=title,
        description=description,
        owner=recipient,
        assigned_to=recipient,
        priority=TodoPriority.HIGH,
        due_date=due_date,
        client=deal.client,
        lead=deal.lead,
        deal=deal,
    )
    return todo


def sync_deal_todos(deal):
    recipient = _deal_recipient(deal)

    _keep_deal_todo(
        deal,
        DEAL_CLOSE_TODO_PREFIX,
        f"{DEAL_CLOSE_TODO_PREFIX}{deal.name}",
        "This deal is expected to close today. Follow up with the customer "
        "or move the expected closing date.",
        deal.expected_close_date,
        recipient,
    )

    action = deal.get_next_action_display() if deal.next_action else ""
    _keep_deal_todo(
        deal,
        DEAL_ACTION_TODO_PREFIX,
        f"{DEAL_ACTION_TODO_PREFIX}{action} - {deal.name}",
        deal.next_action_note or f"{action} the customer about {deal.name}.",
        deal.next_action_date if deal.next_action else None,
        recipient,
    )


@receiver(post_save, sender=Deal)
def keep_deal_reminder_todos(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    sync_deal_todos(instance)
