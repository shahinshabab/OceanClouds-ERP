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
def create_project_todo_when_advance_payment_received(sender, instance, created, **kwargs):
    """
    Advance payment received:
    - No notification needed.
    - Create admin todo to create project.
    """

    if not created:
        return

    if instance.payment_type != PaymentType.ADVANCE:
        return

    invoice = instance.invoice
    deal = invoice.deal if invoice else None
    contract = invoice.contract if invoice else None
    today = timezone.localdate()

    for admin in get_admin_users():
        create_todo_once(
            title=f"Create project for advance payment: {deal or invoice}",
            description=(
                "Advance payment has been received. "
                "Please create a project and assign the project manager."
            ),
            owner=admin,
            assigned_to=admin,
            priority=TodoPriority.HIGH,
            due_date=today,
            deal=deal,
            contract=contract,
            invoice=invoice,
        )
