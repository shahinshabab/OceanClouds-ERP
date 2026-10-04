# sales/approvals.py
"""
Signed contract -> CRM manager approval -> invoice, client and events.

The sales pipeline ends when the customer signs. Signing asks the CRM
managers (admins when there are none) to approve; approving creates the
contract invoice (with the booking advance deducted), the client (new from
the lead, or an existing one picked by the manager) and one event per
contract day.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from common.models import Notification
from common.notifications import notify_user
from common.roles import ROLE_ADMIN, ROLE_CRM_MANAGER
from todos.models import Todo, TodoPriority, TodoStatus
from todos.services import create_todo_once

from .models import ContractStatus, Invoice, InvoiceStatus

APPROVAL_TODO_PREFIX = "Approve invoice and client: "
INVOICE_DUE_DAYS = 7


def contract_approvers():
    users = get_user_model().objects.filter(is_active=True)
    managers = users.filter(groups__name=ROLE_CRM_MANAGER).distinct()
    if managers.exists():
        return managers
    return users.filter(groups__name=ROLE_ADMIN).distinct() or users.filter(is_superuser=True)


def contract_invoice(contract):
    return contract.invoices.filter(is_advance=False).order_by("-issue_date", "-created_at").first()


def needs_approval(contract):
    return (
        contract.status == ContractStatus.SIGNED
        and not contract.approved_at
        and contract_invoice(contract) is None
    )


def _todo_title(contract):
    customer = contract.deal.customer if contract.deal_id else None
    return f"{APPROVAL_TODO_PREFIX}{contract.number or 'contract'}{f' ({customer})' if customer else ''}"


def request_contract_approval(contract, actor=None):
    """Called when a contract becomes signed."""
    if not needs_approval(contract):
        return

    deal = contract.deal
    customer = deal.customer if deal else None
    title = _todo_title(contract)
    for user in contract_approvers():
        notify_user(
            recipient=user,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            notif_type=Notification.Type.CONTRACT_SIGNED,
            target=contract,
            message=f"{customer or 'The customer'} signed contract {contract.number}. "
                    "Approve to create the invoice and client.",
            extra_key="approval",
        )
        create_todo_once(
            title=title,
            description="The contract is signed. Open it, check the details and approve "
                        "to create the invoice, client and events.",
            owner=user,
            assigned_to=user,
            priority=TodoPriority.HIGH,
            due_date=timezone.localdate(),
            client=deal.client if deal else None,
            lead=deal.lead if deal else None,
            deal=deal,
            contract=contract,
        )


@transaction.atomic
def approve_contract(contract, user, client=None):
    """
    Create the invoice, client and events for a signed contract.
    Returns (invoice, client, created_events, skipped_days).
    """
    from .utils import create_client_and_events_from_contract

    deal = contract.deal

    if client is not None and deal.client_id != client.pk:
        deal.client = client
        deal.save(update_fields=["client", "updated_at"])

    invoice = contract_invoice(contract)
    if invoice is None:
        today = timezone.localdate()
        invoice = Invoice.objects.create(
            owner=user,
            deal=deal,
            contract=contract,
            issue_date=today,
            due_date=today + timedelta(days=INVOICE_DUE_DAYS),
            status=InvoiceStatus.ISSUED,
            notes=f"Invoice generated from contract {contract.number}",
        )
        # Carries the contract lines and deducts the booking advance.
        invoice.populate_from_contract(contract, clear_existing=True)

    client, created_events, skipped_days = create_client_and_events_from_contract(contract, user)

    contract.approved_at = timezone.now()
    contract.approved_by = user
    contract.save(update_fields=["approved_at", "approved_by", "updated_at"])

    for todo in Todo.objects.filter(
        contract=contract,
        title__startswith=APPROVAL_TODO_PREFIX,
        status__in=[TodoStatus.PENDING, TodoStatus.IN_PROGRESS],
    ):
        todo.mark_completed()

    return invoice, client, created_events, skipped_days
