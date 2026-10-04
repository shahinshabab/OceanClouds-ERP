# sales/models.py

from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction, IntegrityError
from django.db.models import Case, F, Q, Sum, When
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from common.models import TimeStamped, Owned
from common.numbering import next_sequential_code
from crm.models import Client, Lead
from services.models import Service, Package, DeliverableUnit


# -------------------------------------------------------------------
# Choice enums
# -------------------------------------------------------------------

class DealStage(models.TextChoices):
    NEW = "new", _("New")
    QUALIFIED = "qualified", _("Qualified")
    PROPOSAL_SENT = "proposal_sent", _("Proposal Sent")
    NEGOTIATION = "negotiation", _("Negotiation")
    ADVANCE_RECEIVED = "advance_received", _("Advance Received")
    CONTRACT_SENT = "contract_sent", _("Contract Sent")
    WON = "won", _("Won")
    LOST = "lost", _("Lost")
    ON_HOLD = "on_hold", _("On Hold")


class DealNextAction(models.TextChoices):
    CALL = "call", _("Call")
    WHATSAPP = "whatsapp", _("WhatsApp")
    EMAIL = "email", _("Email")
    MEETING = "meeting", _("Meeting")
    VIDEO_CALL = "video_call", _("Video call")
    SEND_PROPOSAL = "send_proposal", _("Send proposal")
    COLLECT_ADVANCE = "collect_advance", _("Collect advance")
    SEND_CONTRACT = "send_contract", _("Send contract")
    FOLLOW_UP = "follow_up", _("Follow up")
    OTHER = "other", _("Other")


# Stages before the advance; later steps only move a deal forward from here.
OPEN_DEAL_STAGES = (
    DealStage.NEW,
    DealStage.QUALIFIED,
    DealStage.PROPOSAL_SENT,
    DealStage.NEGOTIATION,
)


class ProposalStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    ACCEPTED = "accepted", _("Accepted")
    REJECTED = "rejected", _("Rejected")
    EXPIRED = "expired", _("Expired")


class ContractStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_SIGNATURE = "pending_signature", _("Pending Signature")
    SIGNED = "signed", _("Signed")
    CANCELLED = "cancelled", _("Cancelled")


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ISSUED = "issued", _("Issued")
    PARTIALLY_PAID = "partially_paid", _("Partially Paid")
    PAID = "paid", _("Paid")
    OVERDUE = "overdue", _("Overdue")
    CANCELLED = "cancelled", _("Cancelled")


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    CARD = "card", _("Card")
    UPI = "upi", _("UPI")
    BANK_TRANSFER = "bank_transfer", _("Bank Transfer")
    ONLINE = "online", _("Online Gateway")
    CHEQUE = "cheque", _("Cheque")


class PaymentType(models.TextChoices):
    ADVANCE = "advance", _("Advance")
    INSTALLMENT = "installment", _("Installment / Partial")
    FINAL = "final", _("Final")
    REFUND = "refund", _("Refund")
    OTHER = "other", _("Other")


def net_paid_amount(payments):
    """Money kept from a Payment queryset: refunds count against it."""
    total = payments.aggregate(
        total=Sum(
            Case(
                When(payment_type=PaymentType.REFUND, then=-F("amount")),
                default=F("amount"),
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )["total"]
    return total or Decimal("0.00")


# -------------------------------------------------------------------
# Deal
# -------------------------------------------------------------------

class LeadCustomer:
    """
    Read-only stand-in for a Client while a deal is still running on its lead.

    The client record is created only after the contract is signed, so until
    then proposals, contracts, PDFs and emails show the lead's details through
    this object, which exposes the same attributes templates read from Client.
    """

    is_client = False
    pk = None
    billing_address = ""

    def __init__(self, lead):
        self.lead = lead
        self.name = lead.name or ""
        self.display_name = lead.name or ""
        self.email = lead.email or ""
        self.phone = lead.phone or lead.whatsapp or ""
        self.whatsapp = lead.whatsapp or ""
        self.city = lead.wedding_city or ""
        self.district = lead.wedding_district or ""
        self.state = lead.state or lead.wedding_state or ""
        self.country = lead.country or lead.wedding_country or ""

    def __str__(self):
        return self.display_name or self.name or "Lead"


class Deal(TimeStamped, Owned):
    name = models.CharField(max_length=255)

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="deals",
        null=True,
        blank=True,
    )

    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deals",
    )

    stage = models.CharField(
        max_length=32,
        choices=DealStage.choices,
        default=DealStage.NEW,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    expected_close_date = models.DateField(null=True, blank=True)

    # Next step with the customer; a to-do is kept for it (sales.signals).
    next_action = models.CharField(max_length=32, choices=DealNextAction.choices, blank=True)
    next_action_date = models.DateField(null=True, blank=True)
    next_action_note = models.CharField(max_length=255, blank=True)

    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    closed_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.customer or '-'})"

    def get_absolute_url(self):
        return reverse("sales:deal_detail", args=[self.pk])

    @property
    def customer(self):
        """
        The client once it exists, otherwise the lead's details.
        """

        if self.client_id:
            return self.client

        if self.lead_id:
            return LeadCustomer(self.lead)

        return None

    @property
    def is_open(self):
        return self.stage not in (DealStage.WON, DealStage.LOST)

    @property
    def advance_invoices(self):
        return self.invoices.filter(is_advance=True)

    @property
    def advance_paid(self):
        return net_paid_amount(
            Payment.objects.filter(invoice__deal=self, invoice__is_advance=True)
        )

    @property
    def has_advance(self):
        return self.advance_paid > 0


# -------------------------------------------------------------------
# Proposal
# -------------------------------------------------------------------

class Proposal(TimeStamped, Owned):
    deal = models.ForeignKey(
        Deal,
        on_delete=models.CASCADE,
        related_name="proposals",
    )

    title = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=32,
        choices=ProposalStatus.choices,
        default=ProposalStatus.DRAFT,
    )

    valid_until = models.DateField(null=True, blank=True)

    intro = models.TextField(
        blank=True,
        help_text=_("Personal note to the couple, printed on the cover letter page."),
    )
    terms = models.TextField(
        blank=True,
        help_text=_("One condition per line. Leave blank to use the standard Ocean Clouds terms."),
    )

    accepted_plan = models.ForeignKey(
        "ProposalPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_for_proposals",
        help_text=_("The final plan accepted by the client."),
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("deal", "version")

    def __str__(self):
        return f"Proposal #{self.version} - {self.deal}"

    def get_absolute_url(self):
        return reverse("sales:proposal_detail", args=[self.pk])

    def get_pricing_plan(self):
        """
        Proposal total is based on:
        1. accepted plan, if selected
        2. primary plan, if selected
        3. first plan
        """

        if self.accepted_plan_id:
            return self.accepted_plan

        primary_plan = self.plans.filter(is_primary=True).first()
        if primary_plan:
            return primary_plan

        return self.plans.order_by("sort_order", "id").first()

    def recalculate_totals(self, save=True):
        plan = self.get_pricing_plan()

        if not plan:
            self.subtotal = Decimal("0.00")
            self.discount = Decimal("0.00")
            self.tax_rate = Decimal("0.00")
            self.tax_amount = Decimal("0.00")
            self.total = Decimal("0.00")
        else:
            plan.recalculate_totals(save=True)
            self.subtotal = plan.subtotal
            self.discount = plan.discount
            self.tax_rate = plan.tax_rate
            self.tax_amount = plan.tax_amount
            self.total = plan.total

        if save:
            self.save(
                update_fields=[
                    "subtotal",
                    "discount",
                    "tax_rate",
                    "tax_amount",
                    "total",
                    "updated_at",
                ]
            )

        return self.total

    @transaction.atomic
    def accept_plan(self, plan):
        if plan.proposal_id != self.id:
            raise ValidationError("Selected plan does not belong to this proposal.")

        self.plans.update(is_accepted=False)
        plan.is_accepted = True
        plan.save(update_fields=["is_accepted", "updated_at"])

        self.accepted_plan = plan
        self.status = ProposalStatus.ACCEPTED
        self.save(update_fields=["accepted_plan", "status", "updated_at"])

        # The deal is won only when the contract is signed.
        if self.deal.stage in OPEN_DEAL_STAGES:
            self.deal.stage = DealStage.NEGOTIATION
        self.deal.amount = plan.total
        self.deal.save(update_fields=["stage", "amount", "updated_at"])

        self.recalculate_totals(save=True)


class ProposalPlan(TimeStamped, Owned):
    """
    Proposal can have multiple pricing options.

    Example:
    - Standard Plan
    - Premium Plan
    - Luxury Plan
    """

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="plans",
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    is_primary = models.BooleanField(default=False)
    is_accepted = models.BooleanField(default=False)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["proposal"],
                condition=Q(is_primary=True),
                name="unique_primary_plan_per_proposal",
            ),
            models.UniqueConstraint(
                fields=["proposal"],
                condition=Q(is_accepted=True),
                name="unique_accepted_plan_per_proposal",
            ),
        ]

    def __str__(self):
        return f"{self.proposal} - {self.name}"

    def recalculate_totals(self, save=True):
        subtotal = (
            self.event_days.aggregate(subtotal=Sum("items__line_total"))["subtotal"]
            or Decimal("0.00")
        )

        discount = self.discount or Decimal("0.00")
        tax_rate = self.tax_rate or Decimal("0.00")

        taxable_amount = subtotal - discount
        if taxable_amount < Decimal("0.00"):
            taxable_amount = Decimal("0.00")

        tax_amount = (taxable_amount * tax_rate) / Decimal("100.00")
        total = taxable_amount + tax_amount

        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.total = total

        if save:
            self.save(
                update_fields=[
                    "subtotal",
                    "tax_amount",
                    "total",
                    "updated_at",
                ]
            )

        return total

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.is_primary:
            type(self).objects.filter(
                proposal=self.proposal,
                is_primary=True,
            ).exclude(pk=self.pk).update(is_primary=False)

        if self.is_accepted:
            type(self).objects.filter(
                proposal=self.proposal,
                is_accepted=True,
            ).exclude(pk=self.pk).update(is_accepted=False)


class ProposalEventDay(models.Model):
    """
    Date-wise/event-wise section inside a proposal plan.

    Example:
    - 21 June 2026 - Wedding Eve
    - 22 June 2026 - Main Wedding
    """

    plan = models.ForeignKey(
        ProposalPlan,
        on_delete=models.CASCADE,
        related_name="event_days",
        null=True,
        blank=True,
    )

    event_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=255)
    venue = models.CharField(max_length=255, blank=True)

    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["event_date", "sort_order", "id"]

    def __str__(self):
        if self.event_date:
            return f"{self.event_date} - {self.title}"
        return self.title


class ProposalItem(models.Model):
    """
    Service/package line under a specific proposal event day.
    """

    event_day = models.ForeignKey(
        ProposalEventDay,
        on_delete=models.CASCADE,
        related_name="items",
        null=True,
        blank=True,
    )

    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_items",
    )

    package = models.ForeignKey(
        Package,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_items",
    )

    description = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    @property
    def proposal(self):
        return self.event_day.plan.proposal

    def clean(self):
        if self.service and self.package:
            raise ValidationError("Select either Service or Package, not both.")

        if not self.service and not self.package:
            raise ValidationError("Please select a Service or Package.")

    def _default_description(self):
        if self.service:
            return self.service.name
        if self.package:
            return self.package.name
        return ""

    def _default_unit_price(self):
        if self.service:
            return self.service.base_price or Decimal("0.00")
        if self.package:
            return self.package.selling_price
        return Decimal("0.00")

    def copy_default_deliverables(self):
        """
        Copy service/package default deliverables into proposal item.
        This creates editable proposal-specific deliverables.
        """

        if self.deliverables.exists():
            return

        if self.service:
            for d in self.service.deliverables.filter(is_active=True):
                ProposalItemDeliverable.objects.create(
                    proposal_item=self,
                    title=d.title,
                    description=d.description,
                    quantity=d.quantity,
                    unit=d.unit,
                    sort_order=d.sort_order,
                )

        elif self.package:
            package_deliverables = self.package.deliverables.filter(is_active=True)

            if package_deliverables.exists():
                for d in package_deliverables:
                    ProposalItemDeliverable.objects.create(
                        proposal_item=self,
                        title=d.title,
                        description=d.description,
                        quantity=d.quantity,
                        unit=d.unit,
                        sort_order=d.sort_order,
                    )
            else:
                for package_item in self.package.items.select_related("service").all():
                    if package_item.service:
                        for d in package_item.service.deliverables.filter(is_active=True):
                            ProposalItemDeliverable.objects.create(
                                proposal_item=self,
                                title=d.title,
                                description=d.description,
                                quantity=d.quantity,
                                unit=d.unit,
                                sort_order=d.sort_order,
                            )

    def save(self, *args, **kwargs):
        self.clean()

        if not self.description:
            self.description = self._default_description()

        if self.unit_price is None or self.unit_price == 0:
            self.unit_price = self._default_unit_price()

        self.line_total = (
            (self.unit_price or Decimal("0.00"))
            * Decimal(self.quantity or 0)
        )

        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new:
            self.copy_default_deliverables()

        self.event_day.plan.recalculate_totals(save=True)
        self.event_day.plan.proposal.recalculate_totals(save=True)

    def delete(self, *args, **kwargs):
        plan = self.event_day.plan
        proposal = plan.proposal

        super().delete(*args, **kwargs)

        plan.recalculate_totals(save=True)
        proposal.recalculate_totals(save=True)

    def __str__(self):
        return f"{self.description} x {self.quantity}"


class ProposalItemDeliverable(models.Model):
    proposal_item = models.ForeignKey(
        ProposalItem,
        on_delete=models.CASCADE,
        related_name="deliverables",
        null=True,
        blank=True,
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
    )

    unit = models.CharField(
        max_length=32,
        choices=DeliverableUnit.choices,
        default=DeliverableUnit.ITEM,
    )

    sort_order = models.PositiveIntegerField(default=0)
    is_included = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


# -------------------------------------------------------------------
# Contract
# -------------------------------------------------------------------

class Contract(TimeStamped, Owned):
    CODE_PREFIX = "CTR"
    CODE_PAD = 3

    deal = models.ForeignKey(
        Deal,
        on_delete=models.CASCADE,
        related_name="contracts",
    )

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
    )

    proposal_plan = models.ForeignKey(
        ProposalPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        help_text=_("Accepted proposal plan copied into this contract."),
    )

    number = models.CharField(max_length=64, unique=True, editable=False, blank=True)

    status = models.CharField(
        max_length=32,
        choices=ContractStatus.choices,
        default=ContractStatus.DRAFT,
    )

    signed_date = models.DateField(null=True, blank=True)

    signing_token = models.UUIDField(
        unique=True,
        editable=False,
        null=True,
        blank=True,
        help_text=_("Secure public token used for client signing link."),
    )

    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by_name = models.CharField(max_length=255, blank=True)
    signed_ip_address = models.GenericIPAddressField(null=True, blank=True)
    signed_user_agent = models.TextField(blank=True)

    # After signing, a CRM manager approves before the invoice, client and
    # events are created.
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_contracts",
    )

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    terms = models.TextField(blank=True)
    file = models.FileField(upload_to="contracts/", null=True, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Contract {self.number or '-'} - {self.deal}"

    def get_absolute_url(self):
        return reverse("sales:contract_detail", args=[self.pk])

    def get_public_sign_path(self):
        return reverse("sales:contract_public_sign", args=[self.signing_token])

    def ensure_signing_token(self):
        if not self.signing_token:
            self.signing_token = uuid.uuid4()
            self.save(update_fields=["signing_token", "updated_at"])

    @classmethod
    def _generate_next_number(cls):
        return next_sequential_code(cls, "number", cls.CODE_PREFIX, cls.CODE_PAD)

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.only("number").get(pk=self.pk)
            if old.number:
                self.number = old.number

        if not self.signing_token:
            self.signing_token = uuid.uuid4()

        if self.number:
            return super().save(*args, **kwargs)

        for _attempt in range(10):
            self.number = self._generate_next_number()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.number = ""

        raise IntegrityError("Could not generate unique contract number.")

    def recalculate_totals(self, save=True):
        subtotal = (
            self.event_days.aggregate(subtotal=Sum("items__line_total"))["subtotal"]
            or Decimal("0.00")
        )

        discount = self.discount or Decimal("0.00")
        tax_rate = self.tax_rate or Decimal("0.00")

        taxable_amount = subtotal - discount
        if taxable_amount < Decimal("0.00"):
            taxable_amount = Decimal("0.00")

        tax_amount = (taxable_amount * tax_rate) / Decimal("100.00")
        total = taxable_amount + tax_amount

        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.total = total

        if save:
            self.save(
                update_fields=[
                    "subtotal",
                    "tax_amount",
                    "total",
                    "updated_at",
                ]
            )

        return total

    @transaction.atomic
    def populate_from_proposal(self, proposal, plan=None, clear_existing=False):
        """
        Copy accepted proposal plan into contract.

        This is a snapshot. Later proposal/service/package changes should not
        affect the signed contract.
        """

        if proposal.deal_id != self.deal_id:
            raise ValidationError("Contract deal must match proposal deal.")

        selected_plan = plan or proposal.accepted_plan or proposal.get_pricing_plan()

        if not selected_plan:
            raise ValidationError("Proposal has no plan to copy into contract.")

        if selected_plan.proposal_id != proposal.id:
            raise ValidationError("Selected plan does not belong to this proposal.")

        if clear_existing:
            self.event_days.all().delete()

        self.proposal = proposal
        self.proposal_plan = selected_plan
        self.discount = selected_plan.discount
        self.tax_rate = selected_plan.tax_rate
        if not self.terms and proposal.terms:
            self.terms = proposal.terms
        self.save(
            update_fields=[
                "proposal",
                "proposal_plan",
                "discount",
                "tax_rate",
                "terms",
                "updated_at",
            ]
        )

        for proposal_day in selected_plan.event_days.prefetch_related(
            "items__deliverables"
        ).all():
            contract_day = ContractEventDay.objects.create(
                contract=self,
                proposal_event_day=proposal_day,
                event_date=proposal_day.event_date,
                title=proposal_day.title,
                venue=proposal_day.venue,
                start_time=proposal_day.start_time,
                end_time=proposal_day.end_time,
                notes=proposal_day.notes,
                sort_order=proposal_day.sort_order,
            )

            for proposal_item in proposal_day.items.all():
                contract_item = ContractItem.objects.create(
                    contract_event_day=contract_day,
                    proposal_item=proposal_item,
                    service=proposal_item.service,
                    package=proposal_item.package,
                    description=proposal_item.description,
                    quantity=proposal_item.quantity,
                    unit_price=proposal_item.unit_price,
                    notes=proposal_item.notes,
                    sort_order=proposal_item.sort_order,
                )

                for deliverable in proposal_item.deliverables.all():
                    ContractDeliverable.objects.create(
                        contract_item=contract_item,
                        proposal_deliverable=deliverable,
                        title=deliverable.title,
                        description=deliverable.description,
                        quantity=deliverable.quantity,
                        unit=deliverable.unit,
                        sort_order=deliverable.sort_order,
                        is_included=deliverable.is_included,
                    )

        self.recalculate_totals(save=True)


class ContractEventDay(models.Model):
    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="event_days",
        null=True,
        blank=True,
    )

    proposal_event_day = models.ForeignKey(
        ProposalEventDay,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_event_days",
    )

    event_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=255)
    venue = models.CharField(max_length=255, blank=True)

    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["event_date", "sort_order", "id"]

    def __str__(self):
        if self.event_date:
            return f"{self.event_date} - {self.title}"
        return self.title


class ContractItem(models.Model):
    contract_event_day = models.ForeignKey(
        ContractEventDay,
        on_delete=models.CASCADE,
        related_name="items",
        null=True,
        blank=True,
    )

    proposal_item = models.ForeignKey(
        ProposalItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_items",
    )

    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)

    description = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    @property
    def contract(self):
        return self.contract_event_day.contract

    def save(self, *args, **kwargs):
        if not self.description and self.proposal_item:
            self.description = self.proposal_item.description

        self.line_total = (
            (self.unit_price or Decimal("0.00"))
            * Decimal(self.quantity or 0)
        )

        super().save(*args, **kwargs)
        self.contract.recalculate_totals(save=True)

    def delete(self, *args, **kwargs):
        contract = self.contract
        super().delete(*args, **kwargs)
        contract.recalculate_totals(save=True)

    def __str__(self):
        return f"{self.description} x {self.quantity}"


class ContractDeliverable(models.Model):
    contract_item = models.ForeignKey(
        ContractItem,
        on_delete=models.CASCADE,
        related_name="deliverables",
        null=True,
        blank=True,
    )

    proposal_deliverable = models.ForeignKey(
        ProposalItemDeliverable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_deliverables",
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
    )

    unit = models.CharField(
        max_length=32,
        choices=DeliverableUnit.choices,
        default=DeliverableUnit.ITEM,
    )

    sort_order = models.PositiveIntegerField(default=0)
    is_included = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


# -------------------------------------------------------------------
# Invoice
# -------------------------------------------------------------------

class Invoice(TimeStamped, Owned):
    CODE_PREFIX = "INV"
    CODE_PAD = 3

    deal = models.ForeignKey(
        Deal,
        on_delete=models.CASCADE,
        related_name="invoices",
    )

    contract = models.ForeignKey(
        Contract,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )


    number = models.CharField(max_length=64, unique=True, editable=False, blank=True)

    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=32,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    is_advance = models.BooleanField(
        default=False,
        help_text=_("Booking advance collected before the contract is signed."),
    )
    advance_adjustment = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Advance already received on this deal, deducted from the total."),
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self):
        return f"Invoice {self.number or '-'}"

    def get_absolute_url(self):
        return reverse("sales:invoice_detail", args=[self.pk])

    @property
    def balance(self):
        return (
            (self.total or Decimal("0.00"))
            - (self.amount_paid or Decimal("0.00"))
        )

    def refresh_payment_status(self):
        """Recalculate amount_paid from payments and update the paid status."""
        self.amount_paid = net_paid_amount(self.payments.all())

        if self.status == InvoiceStatus.CANCELLED:
            pass
        elif self.total and self.amount_paid >= self.total:
            self.status = InvoiceStatus.PAID
        elif self.amount_paid > 0:
            self.status = InvoiceStatus.PARTIALLY_PAID
        elif self.status in [InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID]:
            self.status = InvoiceStatus.ISSUED

        self.save(update_fields=["amount_paid", "status", "updated_at"])

    @classmethod
    def _generate_next_number(cls):
        return next_sequential_code(cls, "number", cls.CODE_PREFIX, cls.CODE_PAD)

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.only("number").get(pk=self.pk)
            if old.number:
                self.number = old.number

        if self.number:
            return super().save(*args, **kwargs)

        for _attempt in range(10):
            self.number = self._generate_next_number()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.number = ""

        raise IntegrityError("Could not generate unique invoice number.")

    def recalculate_totals(self, save=True):
        agg = self.items.aggregate(
            subtotal=Sum("line_subtotal"),
        )

        self.subtotal = agg["subtotal"] or Decimal("0.00")

        discount = self.discount or Decimal("0.00")
        tax_rate = self.tax_rate or Decimal("0.00")

        taxable_amount = self.subtotal - discount
        if taxable_amount < Decimal("0.00"):
            taxable_amount = Decimal("0.00")

        self.tax = (taxable_amount * tax_rate) / Decimal("100.00")

        total = taxable_amount + self.tax - (self.advance_adjustment or Decimal("0.00"))
        if total < Decimal("0.00"):
            total = Decimal("0.00")
        self.total = total

        if save:
            self.save(update_fields=["subtotal", "tax", "total", "updated_at"])

        return self.total

    @property
    def gross_total(self):
        """
        Invoice value before the advance adjustment.
        """

        taxable_amount = (self.subtotal or Decimal("0.00")) - (self.discount or Decimal("0.00"))
        if taxable_amount < Decimal("0.00"):
            taxable_amount = Decimal("0.00")

        return taxable_amount + (self.tax or Decimal("0.00"))

    def advance_received(self):
        """Booking advance kept on the deal's advance invoices."""
        return net_paid_amount(
            Payment.objects.filter(invoice__deal_id=self.deal_id, invoice__is_advance=True)
            .exclude(invoice_id=self.pk)
        )

    def refresh_advance_adjustment(self):
        """An advance recorded after the contract invoice still comes off it."""
        if self.is_advance or self.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
            return
        advance = self.advance_received()
        if advance != (self.advance_adjustment or Decimal("0.00")):
            self.advance_adjustment = advance
            self.save(update_fields=["advance_adjustment", "updated_at"])
            self.recalculate_totals(save=True)
            self.refresh_payment_status()

    @transaction.atomic
    def populate_from_contract(self, contract, clear_existing=False):
        """
        Creates invoice from all contract items.
        Useful for full invoice.
        """

        if contract.deal_id != self.deal_id:
            raise ValidationError("Invoice deal must match contract deal.")

        self.contract = contract
        self.discount = contract.discount or Decimal("0.00")
        self.tax_rate = contract.tax_rate or Decimal("0.00")

        # The booking advance was billed on its own invoice before the
        # contract, so the contract invoice only asks for the remainder.
        if not self.is_advance:
            self.advance_adjustment = self.advance_received()

        self.save(
            update_fields=[
                "contract",
                "discount",
                "tax_rate",
                "advance_adjustment",
                "updated_at",
            ]
        )

        if clear_existing:
            self.items.all().delete()

        # Items may only be added to a draft, so an invoice created as
        # issued is treated as a draft (in memory) while it is filled.
        final_status = self.status
        self.status = InvoiceStatus.DRAFT
        try:
            for contract_day in contract.event_days.prefetch_related("items").all():
                for item in contract_day.items.all():
                    InvoiceItem.objects.create(
                        invoice=self,
                        contract_item=item,
                        description=f"{contract_day.title} - {item.description}",
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        tax_rate=Decimal("0.00"),
                    )
        finally:
            self.status = final_status

        self.recalculate_totals(save=True)


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="items",
    )

    contract_item = models.ForeignKey(
        ContractItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_items",
    )

    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]

    def clean(self):
        if self.invoice_id and self.invoice.status != InvoiceStatus.DRAFT:
            raise ValidationError("Cannot modify invoice items after invoice is issued.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.full_clean()

        base = (
            (self.unit_price or Decimal("0.00"))
            * Decimal(self.quantity or 0)
        )

        tax = (
            base
            * (self.tax_rate or Decimal("0.00"))
        ) / Decimal("100.00")

        self.line_subtotal = base
        self.tax_amount = tax
        self.line_total = base + tax

        super().save(*args, **kwargs)
        self.invoice.recalculate_totals(save=True)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self.invoice_id and self.invoice.status != InvoiceStatus.DRAFT:
            raise ValidationError("Cannot delete invoice items after invoice is issued.")

        invoice = self.invoice
        super().delete(*args, **kwargs)
        invoice.recalculate_totals(save=True)

    def __str__(self):
        return f"{self.description} x {self.quantity}"


# -------------------------------------------------------------------
# Payment
# -------------------------------------------------------------------

class Payment(TimeStamped, Owned):
    # PROTECT: deleting an invoice, deal or client must never silently
    # delete the money already received against it.
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    payment_type = models.CharField(
        max_length=32,
        choices=PaymentType.choices,
        default=PaymentType.ADVANCE,
    )

    method = models.CharField(
        max_length=32,
        choices=PaymentMethod.choices,
        default=PaymentMethod.UPI,
    )

    reference = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_received",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.amount} for {self.invoice}"

    def get_absolute_url(self):
        return reverse("sales:invoice_detail", args=[self.invoice_id])

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than zero."})

        if not self.invoice_id or self.amount is None:
            return

        already_paid = net_paid_amount(self.invoice.payments.exclude(pk=self.pk))

        if self.payment_type == PaymentType.REFUND:
            if self.amount > already_paid:
                raise ValidationError(
                    {"amount": f"Refund exceeds the amount paid on this invoice ({already_paid})."}
                )
            return

        remaining = (self.invoice.total or Decimal("0.00")) - already_paid

        if self.amount > remaining:
            raise ValidationError(
                {"amount": f"Payment exceeds remaining balance ({remaining})."}
            )

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.full_clean()

        previous_invoice_id = None
        if self.pk:
            previous_invoice_id = (
                type(self).objects.filter(pk=self.pk).values_list("invoice_id", flat=True).first()
            )

        super().save(*args, **kwargs)
        self.invoice.refresh_payment_status()

        # A payment moved to another invoice must also be taken off the old one.
        if previous_invoice_id and previous_invoice_id != self.invoice_id:
            Invoice.objects.get(pk=previous_invoice_id).refresh_payment_status()

    @transaction.atomic
    def delete(self, *args, **kwargs):
        invoice = self.invoice
        result = super().delete(*args, **kwargs)
        invoice.refresh_payment_status()
        return result


# -------------------------------------------------------------------
# Proposal & contract template
# -------------------------------------------------------------------

class SalesDocumentTemplate(TimeStamped):
    """
    The wording every proposal and contract starts from: the personal note,
    terms, payment terms and payment split. One row, edited by admins and
    CRM managers. A proposal or contract with its own note or terms keeps
    those; otherwise the template is used when the document is generated.
    """

    proposal_note = models.TextField(
        _("proposal personal note"),
        blank=True,
        help_text=_("Opening letter of every proposal. A proposal's own note replaces it."),
    )
    proposal_terms = models.TextField(
        _("proposal terms"),
        blank=True,
        help_text=_("One condition per line. The payment split line is added for you."),
    )
    contract_note = models.TextField(
        _("contract note"),
        blank=True,
        help_text=_("Short paragraph under the parties on the first page."),
    )
    contract_terms = models.TextField(
        _("contract terms"),
        blank=True,
        help_text=_("One condition per line. A contract's own terms replace these."),
    )
    good_to_know = models.TextField(
        _("good to know"),
        blank=True,
        help_text=_("Practical notes for the couple, one per line."),
    )
    payment_terms = models.TextField(
        _("payment terms"),
        blank=True,
        help_text=_("One per line, shown with the payment schedule."),
    )
    advance_percent = models.PositiveSmallIntegerField(_("booking advance %"), default=10)
    event_percent = models.PositiveSmallIntegerField(_("on the event day %"), default=30)
    delivery_percent = models.PositiveSmallIntegerField(_("on delivery %"), default=60)

    class Meta:
        verbose_name = _("proposal & contract template")
        verbose_name_plural = _("proposal & contract template")

    def __str__(self):
        return "Proposal & contract template"

    def clean(self):
        total = (self.advance_percent or 0) + (self.event_percent or 0) + (self.delivery_percent or 0)
        if total != 100:
            raise ValidationError(_("The three payment percentages must add up to 100 (now %(total)s).") % {"total": total})

    @classmethod
    def load(cls):
        template = cls.objects.order_by("pk").first()
        if template:
            return template

        from . import document_defaults as d

        return cls.objects.create(
            proposal_note=d.PROPOSAL_NOTE,
            proposal_terms="\n".join(d.PROPOSAL_TERMS),
            contract_note=d.CONTRACT_NOTE,
            contract_terms="\n".join(d.CONTRACT_TERMS),
            good_to_know="\n".join(d.GOOD_TO_KNOW),
            payment_terms="\n".join(d.PAYMENT_TERMS),
            advance_percent=d.ADVANCE_PERCENT,
            event_percent=d.EVENT_PERCENT,
            delivery_percent=d.DELIVERY_PERCENT,
        )
