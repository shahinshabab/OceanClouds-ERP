from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from common.roles import ROLE_ADMIN
from todos.models import TodoPriority
from todos.services import create_todo_once

from .models import Payment, PaymentType


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
