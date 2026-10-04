import json
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from common.mixins import ContractViewAccessMixin, SalesAccessMixin, SalesReadOnlyAccessMixin
from common.roles import can_access_sales
from crm.models import Lead
from messaging.models import EmailTemplate
from messaging.utils import EmailSendError, send_templated_email
from services.models import Service, Package

from .forms import (
    AdvancePaymentForm,
    DealForm,
    ProposalForm,
    ProposalPlanForm,
    ProposalEventDayForm,
    ProposalItemForm,
    ProposalItemDeliverableForm,
    ContractForm,
    InvoiceForm,
    PaymentForm,
    get_catalog_choices,
)
from .models import (
    Deal,
    Proposal,
    ProposalEventDay,
    Contract,
    Invoice,
    InvoiceItem,
    Payment,
    PaymentType,
    DealStage,
    OPEN_DEAL_STAGES,
    ProposalStatus,
    ContractStatus,
    InvoiceStatus,
)
from .utils import (
    ADVANCE_PERCENT,
    DELIVERY_PERCENT,
    EVENT_PERCENT,
    build_common_email_context,
    build_contract_document_context,
    build_proposal_document_context,
    check_before_send,
    create_client_and_events_from_contract,
    flash_send_result,
    get_amount_in_words,
    get_contract_client,
    get_contract_pdf_total,
    get_contract_public_sign_total,
    get_oceanclouds_bank_details,
    get_payment_plan_client_notes,
    get_payment_plan_deliverable_rows,
    get_payment_plan_important_terms,
    get_payment_plan_terms,
    get_pdf_deliverables,
    get_pdf_event_days,
    get_proposal_client,
    get_proposal_terms,
    get_selected_proposal_plan,
    lead_status,
    percentage_amount,
    resolve_client_email,
    resolve_primary_contact,
    set_lead_status,
)

from common.pdf import HTML, render_pdf


class OwnerAssignMixin:
    """
    Automatically assigns owner for models using common.models.Owned.
    """

    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user

        return super().form_valid(form)


def _contract_has_invoice(contract):
    return contract.invoices.exists()


def mark_deal_won(deal):
    """
    Signing the contract closes the deal as won.
    """

    deal.stage = DealStage.WON
    deal.closed_on = deal.closed_on or timezone.localdate()
    deal.is_active = True
    deal.save(update_fields=["stage", "closed_on", "is_active", "updated_at"])


def _get_price_maps():
    services_price_map = {
        str(s.id): str(s.base_price or Decimal("0.00"))
        for s in Service.objects.all().only("id", "base_price").order_by("id")
    }

    packages_price_map = {
        str(p.id): str(p.selling_price)
        for p in Package.objects.all().only("id", "total_price", "price").order_by("id")
    }

    return services_price_map, packages_price_map


def _get_proposal_plan(proposal):
    return proposal.accepted_plan or proposal.get_pricing_plan()


def _get_proposal_event_day(proposal):
    plan = _get_proposal_plan(proposal)
    if not plan:
        return None
    return plan.event_days.order_by("sort_order", "event_date", "id").first()


def _iter_proposal_event_days(proposal):
    plan = _get_proposal_plan(proposal)
    if not plan:
        return ProposalEventDay.objects.none()

    return (
        plan.event_days
        .prefetch_related(
            "items",
            "items__service",
            "items__package",
            "items__deliverables",
        )
        .all()
    )

class DetailMessageScopeMixin:
    """
    Adds one message scope to every detail page.

    Example:
    detail_message_scope = "scope:contract"

    Then the template can show only messages that match:
    - scope:contract
    - scope:email
    - scope:global
    """

    detail_message_scope = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["detail_message_scope"] = self.detail_message_scope
        return context


def _scope_tags(*scopes):
    """
    Usage:
        _scope_tags("contract", "email")
        returns: "scope:contract scope:email"

    Also accepts already-prefixed values:
        _scope_tags("scope:contract", "scope:email")
    """

    tags = []

    for scope in scopes:
        if not scope:
            continue

        scope = str(scope).strip()

        if not scope:
            continue

        if scope.startswith("scope:"):
            tags.append(scope)
        else:
            tags.append(f"scope:{scope}")

    return " ".join(tags)


def _safe_filename_part(value, fallback):
    return slugify(str(value or "").strip()) or fallback


def _pdf_filename(*parts):
    safe_parts = [
        _safe_filename_part(part, "file").upper()
        for part in parts
        if str(part or "").strip()
    ]
    return f"{'-'.join(safe_parts)}.PDF"


def _client_filename_part(obj):
    deal = getattr(obj, "deal", None)
    client = getattr(deal, "client", None) if deal else None

    if client:
        name = (
            getattr(client, "display_name", None)
            or getattr(client, "name", None)
            or str(client)
        )
    elif deal:
        name = getattr(deal, "name", None) or str(deal)
    else:
        name = "client"

    return _safe_filename_part(name, "client")

# ============================================================
# Deals
# ============================================================

class DealListView(SalesAccessMixin, ListView):
    model = Deal
    template_name = "sales/deal_list.html"
    context_object_name = "deals"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("client", "lead", "owner")

        q = (self.request.GET.get("q") or "").strip()
        stage = (self.request.GET.get("stage") or "").strip()
        is_active = (self.request.GET.get("is_active") or "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(client__name__icontains=q)
                | Q(client__display_name__icontains=q)
                | Q(lead__name__icontains=q)
                | Q(description__icontains=q)
            )

        if stage:
            qs = qs.filter(stage=stage)

        if is_active == "true":
            qs = qs.filter(is_active=True)
        elif is_active == "false":
            qs = qs.filter(is_active=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = self.request.GET.get("q", "")
        context["filter_stage"] = self.request.GET.get("stage", "")
        context["filter_is_active"] = self.request.GET.get("is_active", "")
        context["stage_choices"] = DealStage.choices
        context["is_active_choices"] = [
            ("", "All"),
            ("true", "Active only"),
            ("false", "Inactive only"),
        ]

        return context


class DealDetailView(SalesReadOnlyAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Deal
    template_name = "sales/deal_detail.html"
    context_object_name = "deal"
    detail_message_scope = "scope:deal"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("client", "lead", "owner")
            .prefetch_related(
                "proposals",
                "proposals__plans",
                "proposals__plans__event_days",
                "proposals__plans__event_days__items",
                "contracts",
                "contracts__event_days",
                "contracts__event_days__items",
                "invoices",
                "invoices__payments",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["proposals"] = self.object.proposals.all().order_by("-created_at")
        context["contracts"] = self.object.contracts.all().order_by("-created_at")
        context["invoices"] = self.object.invoices.all().order_by("-issue_date", "-id")

        return context


class DealCreateView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    model = Deal
    form_class = DealForm
    template_name = "sales/deal_form.html"

    def get_initial(self):
        initial = super().get_initial()

        client_id = self.request.GET.get("client")
        lead_id = self.request.GET.get("lead")

        if client_id:
            initial["client"] = client_id

        if lead_id:
            lead = Lead.objects.filter(pk=lead_id).first()

            if lead:
                initial.update(
                    {
                        "lead": lead.pk,
                        # Important:
                        # Do not create or assign client here.
                        # Client is created only after the contract is signed.
                        "name": f"{lead.name} Wedding Deal",
                        "amount": lead.budget_max or lead.budget_min,
                        "expected_close_date": lead.wedding_date,
                        "description": lead.notes,
                        "stage": DealStage.NEW,
                    }
                )

        return initial

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        if self.object.lead_id:
            lead = self.object.lead

            lead.status = lead_status("STATUS_CONVERTED_TO_DEAL", "converted_to_deal")
            lead.save(update_fields=["status", "updated_at"])

        messages.success(
            self.request,
            "Deal created successfully.",
            extra_tags=_scope_tags("deal"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:deal_detail", kwargs={"pk": self.object.pk})


class DealUpdateView(SalesAccessMixin, OwnerAssignMixin, UpdateView):
    model = Deal
    form_class = DealForm
    template_name = "sales/deal_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "lead", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Deal updated successfully.",
            extra_tags=_scope_tags("deal"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:deal_detail", kwargs={"pk": self.object.pk})
    
class DealDeleteView(SalesAccessMixin, DeleteView):
    model = Deal
    template_name = "common/confirm_delete.html"
    success_url = reverse_lazy("sales:deal_list")

    def get_queryset(self):
        return super().get_queryset().select_related("client", "lead", "owner")

    def form_valid(self, form):
        messages.success(
            self.request,
            "Deal deleted successfully.",
            extra_tags=_scope_tags("deal"),
        )
        return super().form_valid(form)


class LeadConvertToDealView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    """
    Flow:
    Lead detail page -> Convert to Deal.

    Important:
    This does NOT create a client.
    Client is created only after the contract is signed and invoiced,
    from the contract's Create Client & Event button.
    """

    model = Deal
    form_class = DealForm
    template_name = "sales/deal_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.lead = get_object_or_404(
            Lead.objects.select_related("client", "owner", "inquiry"),
            pk=self.kwargs["pk"],
        )

        existing_deal = self.lead.deals.order_by("-created_at").first()
        if existing_deal:
            messages.info(
                request,
                "This lead already has a deal.",
                extra_tags=_scope_tags("deal"),
            )
            return redirect("sales:deal_detail", pk=existing_deal.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()

        amount = self.lead.budget_max or self.lead.budget_min

        initial.update(
            {
                "lead": self.lead.pk,
                # Important:
                # Do not assign client here.
                "name": f"{self.lead.name} Wedding Deal",
                "amount": amount,
                "expected_close_date": self.lead.wedding_date,
                "description": self.lead.notes,
                "stage": DealStage.NEW,
                "is_active": True,
            }
        )

        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["source_lead"] = self.lead
        context["is_lead_conversion"] = True

        return context

    @transaction.atomic
    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user

        response = super().form_valid(form)

        self.lead.status = lead_status("STATUS_CONVERTED_TO_DEAL", "converted_to_deal")
        self.lead.save(update_fields=["status", "updated_at"])

        messages.success(
            self.request,
            "Lead converted to deal successfully.",
            extra_tags=_scope_tags("deal"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:deal_detail", kwargs={"pk": self.object.pk})

# ============================================================
# Proposals
# ============================================================

class ProposalListView(SalesAccessMixin, ListView):
    model = Proposal
    template_name = "sales/proposal_list.html"
    context_object_name = "proposals"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("deal", "deal__client", "owner")

        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        deal_stage = (self.request.GET.get("deal_stage") or "").strip()

        if q:
            qs = qs.filter(
                Q(deal__name__icontains=q)
                | Q(deal__client__name__icontains=q)
                | Q(deal__lead__name__icontains=q)
                | Q(title__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if deal_stage:
            qs = qs.filter(deal__stage=deal_stage)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = self.request.GET.get("q", "")
        context["filter_status"] = self.request.GET.get("status", "")
        context["filter_deal_stage"] = self.request.GET.get("deal_stage", "")
        context["status_choices"] = ProposalStatus.choices
        context["deal_stage_choices"] = DealStage.choices

        return context


class ProposalDetailView(SalesReadOnlyAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Proposal
    template_name = "sales/proposal_detail.html"
    context_object_name = "proposal"
    detail_message_scope = "scope:proposal"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "deal__lead", "owner")
            .prefetch_related(
                "plans",
                "plans__event_days",
                "plans__event_days__items",
                "plans__event_days__items__service",
                "plans__event_days__items__package",
                "plans__event_days__items__deliverables",
                "contracts",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["pdf_download_url"] = reverse("sales:proposal_pdf_download", args=[self.object.pk])
        context["has_contract"] = self.object.contracts.exists()
        context["contract"] = self.object.contracts.order_by("-created_at").first()
        context["pricing_plan"] = _get_proposal_plan(self.object)
        context["event_days"] = _iter_proposal_event_days(self.object)

        return context









class ProposalPDFDownloadView(SalesAccessMixin, DetailView):
    model = Proposal

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "deal",
                "deal__client",
                "owner",
                "accepted_plan",
            )
            .prefetch_related(
                "plans",
                "plans__event_days",
                "plans__event_days__items",
                "plans__event_days__items__service",
                "plans__event_days__items__package",
                "plans__event_days__items__deliverables",
            )
        )

    def get(self, request, *args, **kwargs):
        proposal = self.get_object()

        try:
            pdf_bytes = render_pdf(
                "sales/proposal_pdf.html",
                build_proposal_document_context(proposal),
                request=request,
            )
        except Exception as exc:
            raise Http404(f"Could not generate proposal PDF: {exc}")

        client_name = _client_filename_part(proposal)
        version = f"V{proposal.version or 1}"
        filename = _pdf_filename("PROPOSAL", client_name, version)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ProposalDocumentView(SalesReadOnlyAccessMixin, DetailView):
    """
    The proposal in the browser: the same document as the PDF.
    """

    model = Proposal

    def get(self, request, *args, **kwargs):
        proposal = self.get_object()
        context = build_proposal_document_context(proposal)
        context["screen"] = True
        return render(request, "sales/proposal_pdf.html", context)


class ProposalCreateView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    model = Proposal
    form_class = ProposalForm
    template_name = "sales/proposal_form.html"

    default_plan_initial = {
        "name": "Standard Plan",
        "is_primary": True,
        "sort_order": 0,
    }

    default_event_initial = {
        "title": "Wedding Event",
        "sort_order": 0,
    }

    def get_initial(self):
        initial = super().get_initial()

        deal_id = self.request.GET.get("deal")
        if deal_id:
            deal = Deal.objects.filter(pk=deal_id).select_related("client").first()

            if deal:
                next_version = deal.proposals.count() + 1

                initial.update(
                    {
                        "deal": deal.pk,
                        "title": f"Proposal for {deal.name}",
                        "version": next_version,
                        "status": ProposalStatus.DRAFT,
                    }
                )

        return initial

    def get_proposal_object(self):
        return getattr(self, "object", None)

    def get_plan(self):
        proposal = self.get_proposal_object()
        if not proposal:
            return None

        return _get_proposal_plan(proposal)

    def get_catalog_choices(self):
        return get_catalog_choices()

    def get_deliverable_maps(self):
        services = {}
        for service in Service.objects.filter(is_active=True).prefetch_related("deliverables"):
            services[str(service.pk)] = [
                {
                    "title": deliverable.title,
                    "description": deliverable.description,
                    "quantity": str(deliverable.quantity),
                    "unit": deliverable.unit,
                    "sort_order": deliverable.sort_order,
                    "is_included": True,
                }
                for deliverable in service.deliverables.filter(is_active=True)
            ]

        packages = {}
        for package in Package.objects.filter(is_active=True).prefetch_related(
            "deliverables",
            "items__service__deliverables",
        ):
            package_deliverables = list(package.deliverables.filter(is_active=True))

            if package_deliverables:
                packages[str(package.pk)] = [
                    {
                        "title": deliverable.title,
                        "description": deliverable.description,
                        "quantity": str(deliverable.quantity),
                        "unit": deliverable.unit,
                        "sort_order": deliverable.sort_order,
                        "is_included": True,
                    }
                    for deliverable in package_deliverables
                ]
            else:
                copied = []
                sort_order = 0
                for package_item in package.items.select_related("service").prefetch_related("service__deliverables"):
                    if not package_item.service_id:
                        continue

                    for deliverable in package_item.service.deliverables.filter(is_active=True):
                        copied.append(
                            {
                                "title": deliverable.title,
                                "description": deliverable.description,
                                "quantity": str(deliverable.quantity),
                                "unit": deliverable.unit,
                                "sort_order": sort_order,
                                "is_included": True,
                            }
                        )
                        sort_order += 1

                packages[str(package.pk)] = copied

        return services, packages

    def _post_int(self, key, default=0):
        try:
            return int(self.request.POST.get(key, default))
        except (TypeError, ValueError):
            return default

    def _get_event_instance(self, plan, prefix):
        if not plan:
            return None

        event_id = self.request.POST.get(f"{prefix}-id")
        if not event_id:
            return None

        return plan.event_days.filter(pk=event_id).first()

    def _get_item_instance(self, event_day, prefix):
        if not event_day:
            return None

        item_id = self.request.POST.get(f"{prefix}-id")
        if not item_id:
            return None

        return event_day.items.filter(pk=item_id).first()

    def _get_deliverable_instance(self, item, prefix):
        if not item:
            return None

        deliverable_id = self.request.POST.get(f"{prefix}-id")
        if not deliverable_id:
            return None

        return item.deliverables.filter(pk=deliverable_id).first()

    def _is_deleted(self, prefix):
        return self.request.POST.get(f"{prefix}-DELETE") in {"on", "true", "1"}

    def _item_has_data(self, prefix):
        fields = ["catalog_item", "description", "notes"]
        return any((self.request.POST.get(f"{prefix}-{field}") or "").strip() for field in fields)

    def _deliverable_has_data(self, prefix):
        fields = ["title", "description"]
        return any((self.request.POST.get(f"{prefix}-{field}") or "").strip() for field in fields)

    def build_nested_forms(self, plan=None):
        catalog_choices = self.get_catalog_choices()

        if self.request.method == "POST":
            event_entries = []
            event_total = self._post_int("events-TOTAL_FORMS", 0)

            for event_index in range(event_total):
                event_prefix = f"event-{event_index}"
                event_instance = self._get_event_instance(plan, event_prefix)
                event_form = ProposalEventDayForm(
                    self.request.POST,
                    instance=event_instance,
                    prefix=event_prefix,
                )

                item_entries = []
                item_total = self._post_int(f"{event_prefix}-items-TOTAL_FORMS", 0)

                for item_index in range(item_total):
                    item_prefix = f"{event_prefix}-item-{item_index}"
                    item_instance = self._get_item_instance(event_instance, item_prefix)
                    item_form = ProposalItemForm(
                        self.request.POST,
                        instance=item_instance,
                        prefix=item_prefix,
                        catalog_choices=catalog_choices,
                    )

                    deliverable_entries = []
                    deliverable_total = self._post_int(f"{item_prefix}-deliverables-TOTAL_FORMS", 0)

                    for deliverable_index in range(deliverable_total):
                        deliverable_prefix = f"{item_prefix}-deliverable-{deliverable_index}"
                        deliverable_instance = self._get_deliverable_instance(
                            item_instance,
                            deliverable_prefix,
                        )
                        deliverable_form = ProposalItemDeliverableForm(
                            self.request.POST,
                            instance=deliverable_instance,
                            prefix=deliverable_prefix,
                        )
                        deliverable_entries.append(
                            {
                                "form": deliverable_form,
                                "prefix": deliverable_prefix,
                                "instance": deliverable_instance,
                                "delete": self._is_deleted(deliverable_prefix),
                                "has_data": self._deliverable_has_data(deliverable_prefix),
                            }
                        )

                    item_entries.append(
                        {
                            "form": item_form,
                            "prefix": item_prefix,
                            "instance": item_instance,
                            "delete": self._is_deleted(item_prefix),
                            "has_data": self._item_has_data(item_prefix),
                            "deliverables": deliverable_entries,
                        }
                    )

                event_entries.append(
                    {
                        "form": event_form,
                        "prefix": event_prefix,
                        "instance": event_instance,
                        "delete": self._is_deleted(event_prefix),
                        "items": item_entries,
                    }
                )

            return event_entries

        if plan:
            event_entries = []
            for event_index, event_day in enumerate(
                plan.event_days.prefetch_related(
                    "items",
                    "items__service",
                    "items__package",
                    "items__deliverables",
                ).all()
            ):
                event_prefix = f"event-{event_index}"
                item_entries = []

                for item_index, item in enumerate(event_day.items.all()):
                    item_prefix = f"{event_prefix}-item-{item_index}"
                    deliverable_entries = []

                    for deliverable_index, deliverable in enumerate(item.deliverables.all()):
                        deliverable_prefix = f"{item_prefix}-deliverable-{deliverable_index}"
                        deliverable_entries.append(
                            {
                                "form": ProposalItemDeliverableForm(
                                    instance=deliverable,
                                    prefix=deliverable_prefix,
                                ),
                                "prefix": deliverable_prefix,
                                "instance": deliverable,
                                "delete": False,
                                "has_data": True,
                            }
                        )

                    if not deliverable_entries:
                        deliverable_prefix = f"{item_prefix}-deliverable-0"
                        deliverable_entries.append(
                            {
                                "form": ProposalItemDeliverableForm(prefix=deliverable_prefix),
                                "prefix": deliverable_prefix,
                                "instance": None,
                                "delete": False,
                                "has_data": False,
                            }
                        )

                    item_entries.append(
                        {
                            "form": ProposalItemForm(
                                instance=item,
                                prefix=item_prefix,
                                catalog_choices=catalog_choices,
                            ),
                            "prefix": item_prefix,
                            "instance": item,
                            "delete": False,
                            "has_data": True,
                            "deliverables": deliverable_entries,
                        }
                    )

                if not item_entries:
                    item_prefix = f"{event_prefix}-item-0"
                    item_entries.append(
                        {
                            "form": ProposalItemForm(
                                prefix=item_prefix,
                                catalog_choices=catalog_choices,
                            ),
                            "prefix": item_prefix,
                            "instance": None,
                            "delete": False,
                            "has_data": False,
                            "deliverables": [
                                {
                                    "form": ProposalItemDeliverableForm(
                                        prefix=f"{item_prefix}-deliverable-0"
                                    ),
                                    "prefix": f"{item_prefix}-deliverable-0",
                                    "instance": None,
                                    "delete": False,
                                    "has_data": False,
                                }
                            ],
                        }
                    )

                event_entries.append(
                    {
                        "form": ProposalEventDayForm(
                            instance=event_day,
                            prefix=event_prefix,
                        ),
                        "prefix": event_prefix,
                        "instance": event_day,
                        "delete": False,
                        "items": item_entries,
                    }
                )

            if event_entries:
                return event_entries

        event_prefix = "event-0"
        item_prefix = f"{event_prefix}-item-0"
        deliverable_prefix = f"{item_prefix}-deliverable-0"
        return [
            {
                "form": ProposalEventDayForm(
                    prefix=event_prefix,
                    initial=self.default_event_initial,
                ),
                "prefix": event_prefix,
                "instance": None,
                "delete": False,
                "items": [
                    {
                        "form": ProposalItemForm(
                            prefix=item_prefix,
                            catalog_choices=catalog_choices,
                        ),
                        "prefix": item_prefix,
                        "instance": None,
                        "delete": False,
                        "has_data": False,
                        "deliverables": [
                            {
                                "form": ProposalItemDeliverableForm(prefix=deliverable_prefix),
                                "prefix": deliverable_prefix,
                                "instance": None,
                                "delete": False,
                                "has_data": False,
                            }
                        ],
                    }
                ],
            }
        ]

    def validate_nested_forms(self, event_entries):
        is_valid = True

        for event_entry in event_entries:
            if event_entry["delete"]:
                continue

            if not event_entry["form"].is_valid():
                is_valid = False

            for item_entry in event_entry["items"]:
                if item_entry["delete"]:
                    continue

                if not item_entry["has_data"] and not item_entry["instance"]:
                    continue

                if not item_entry["form"].is_valid():
                    is_valid = False

                for deliverable_entry in item_entry["deliverables"]:
                    if deliverable_entry["delete"]:
                        continue

                    if not deliverable_entry["has_data"] and not deliverable_entry["instance"]:
                        continue

                    if not deliverable_entry["form"].is_valid():
                        is_valid = False

        return is_valid

    def save_nested_forms(self, plan, event_entries):
        for event_entry in event_entries:
            event_instance = event_entry["instance"]

            if event_entry["delete"]:
                if event_instance:
                    event_instance.delete()
                continue

            event_day = event_entry["form"].save(commit=False)
            event_day.plan = plan
            event_day.save()

            for item_entry in event_entry["items"]:
                item_instance = item_entry["instance"]

                if item_entry["delete"]:
                    if item_instance:
                        item_instance.delete()
                    continue

                if not item_entry["has_data"] and not item_instance:
                    continue

                item = item_entry["form"].save(commit=False)
                item.event_day = event_day
                item.save()

                active_deliverable_entries = [
                    deliverable_entry
                    for deliverable_entry in item_entry["deliverables"]
                    if (
                        not deliverable_entry["delete"]
                        and (
                            deliverable_entry["has_data"]
                            or deliverable_entry["instance"]
                        )
                    )
                ]
                has_explicit_deliverables = any(
                    deliverable_entry["has_data"]
                    or deliverable_entry["instance"]
                    or deliverable_entry["delete"]
                    for deliverable_entry in item_entry["deliverables"]
                )

                if active_deliverable_entries or has_explicit_deliverables:
                    item.deliverables.all().delete()

                    for deliverable_entry in active_deliverable_entries:
                        deliverable = deliverable_entry["form"].save(commit=False)
                        deliverable.proposal_item = item
                        deliverable.save()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        services_price_map, packages_price_map = _get_price_maps()
        context["services_price_map_json"] = mark_safe(json.dumps(services_price_map))
        context["packages_price_map_json"] = mark_safe(json.dumps(packages_price_map))
        services_deliverable_map, packages_deliverable_map = self.get_deliverable_maps()
        context["services_deliverable_map_json"] = mark_safe(json.dumps(services_deliverable_map))
        context["packages_deliverable_map_json"] = mark_safe(json.dumps(packages_deliverable_map))

        catalog_choices = self.get_catalog_choices()
        plan = self.get_plan()

        if self.request.method == "POST":
            context["plan_form"] = ProposalPlanForm(
                self.request.POST,
                instance=plan,
                prefix="plan",
            )
        else:
            context["plan_form"] = ProposalPlanForm(
                instance=plan,
                prefix="plan",
                initial=self.default_plan_initial,
            )

        context["event_entries"] = self.build_nested_forms(plan=plan)
        context["empty_event_form"] = ProposalEventDayForm(prefix="event-__event__")
        context["empty_item_form"] = ProposalItemForm(
            prefix="event-__event__-item-__item__",
            catalog_choices=catalog_choices,
        )
        context["empty_deliverable_form"] = ProposalItemDeliverableForm(
            prefix="event-__event__-item-__item__-deliverable-__deliverable__"
        )

        return context

    @transaction.atomic
    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user

        context = self.get_context_data(form=form)
        plan_form = context["plan_form"]
        event_entries = context["event_entries"]

        if not (plan_form.is_valid() and self.validate_nested_forms(event_entries)):
            return self.render_to_response(context)

        self.object = form.save()

        plan = plan_form.save(commit=False)
        plan.proposal = self.object
        if hasattr(plan, "owner") and not plan.owner_id:
            plan.owner = self.request.user
        plan.save()

        self.save_nested_forms(plan, event_entries)

        self.object.recalculate_totals(save=True)

        deal = self.object.deal
        deal.stage = DealStage.PROPOSAL_SENT
        deal.save(update_fields=["stage", "updated_at"])

        if deal.lead_id:
            lead = deal.lead
            set_lead_status(lead, "STATUS_PROPOSAL_SENT", "proposal_sent")

        messages.success(
            self.request,
            "Proposal created successfully.",
            extra_tags=_scope_tags("proposal"),
        )

        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy("sales:proposal_detail", kwargs={"pk": self.object.pk})


class ProposalUpdateView(SalesAccessMixin, OwnerAssignMixin, UpdateView):
    model = Proposal
    form_class = ProposalForm
    template_name = "sales/proposal_form.html"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "owner")
            .prefetch_related(
                "plans",
                "plans__event_days",
                "plans__event_days__items",
                "plans__event_days__items__deliverables",
            )
        )

    @transaction.atomic
    def form_valid(self, form):
        context = self.get_context_data(form=form)
        plan_form = context["plan_form"]
        event_entries = context["event_entries"]

        if not (plan_form.is_valid() and self.validate_nested_forms(event_entries)):
            return self.render_to_response(context)

        self.object = form.save()

        plan = plan_form.save(commit=False)
        plan.proposal = self.object
        if hasattr(plan, "owner") and not plan.owner_id:
            plan.owner = self.request.user
        plan.save()

        self.save_nested_forms(plan, event_entries)

        self.object.recalculate_totals(save=True)

        messages.success(
            self.request,
            "Proposal updated successfully.",
            extra_tags=_scope_tags("proposal"),
        )

        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy("sales:proposal_detail", kwargs={"pk": self.object.pk})

class ProposalDeleteView(SalesAccessMixin, DeleteView):
    model = Proposal
    template_name = "common/confirm_delete.html"
    success_url = reverse_lazy("sales:proposal_list")

    def get_queryset(self):
        return super().get_queryset().select_related("deal", "deal__client", "owner")

    def form_valid(self, form):
        messages.success(
            self.request,
            "Proposal deleted successfully.",
            extra_tags=_scope_tags("proposal"),
        )
        return super().form_valid(form)

@method_decorator(require_POST, name="dispatch")
class ProposalAcceptView(SalesAccessMixin, View):
    """
    Proposal accepted:
    - Proposal status = accepted
    - Deal stage = negotiation (won only when the contract is signed)
    - Lead status = proposal accepted
    - Does NOT create client; next step is recording the advance
    """

    @transaction.atomic
    def post(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("deal", "deal__client", "deal__lead"),
            pk=pk,
        )

        deal = proposal.deal
        lead = deal.lead
        plan = proposal.get_pricing_plan()

        if plan:
            proposal.accept_plan(plan)
        else:
            proposal.status = ProposalStatus.ACCEPTED
            proposal.save(update_fields=["status", "updated_at"])

        deal.refresh_from_db()
        if deal.stage in OPEN_DEAL_STAGES:
            deal.stage = DealStage.NEGOTIATION
        if plan:
            deal.amount = plan.total
        deal.is_active = True
        deal.save(update_fields=["stage", "amount", "is_active", "updated_at"])

        if lead:
            set_lead_status(lead, "STATUS_PROPOSAL_ACCEPTED", "proposal_accepted")

        messages.success(
            request,
            "Proposal accepted. Next, record the advance payment.",
            extra_tags=_scope_tags("proposal"),
        )

        return redirect("sales:proposal_detail", pk=proposal.pk)

class ProposalConvertToContractView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    """
    Proposal detail page -> Convert to Contract.

    Contract can be created once the proposal is accepted. The advance is
    normally recorded first; without it the contract is still allowed but
    the user is warned. No client is needed at this stage.
    """

    model = Contract
    form_class = ContractForm
    template_name = "sales/contract_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.proposal = get_object_or_404(
            Proposal.objects.select_related(
                "deal",
                "deal__client",
                "deal__lead",
            ),
            pk=self.kwargs["pk"],
        )

        deal = self.proposal.deal

        # 1. Proposal must be accepted first
        if self.proposal.status != ProposalStatus.ACCEPTED:
            messages.error(
                request,
                "Please accept the proposal before creating a contract.",
                extra_tags=_scope_tags("proposal"),
            )
            return redirect("sales:proposal_detail", pk=self.proposal.pk)

        # 2. Prevent duplicate contract
        existing_contract = self.proposal.contracts.order_by("-created_at").first()
        if existing_contract:
            messages.info(
                request,
                "This proposal already has a contract.",
                extra_tags=_scope_tags("contract"),
            )
            return redirect("sales:contract_detail", pk=existing_contract.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        selected_plan = self.proposal.accepted_plan or self.proposal.get_pricing_plan()

        initial.update(
            {
                "deal": self.proposal.deal_id,
                "proposal": self.proposal.pk,
                "proposal_plan": selected_plan.pk if selected_plan else None,
                "status": ContractStatus.DRAFT,
                "start_date": timezone.localdate(),
                "terms": self.proposal.terms,
            }
        )

        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["source_proposal"] = self.proposal
        context["is_proposal_conversion"] = True

        return context

    @transaction.atomic
    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user

        response = super().form_valid(form)

        self.object.populate_from_proposal(
            self.proposal,
            plan=self.object.proposal_plan,
            clear_existing=True,
        )

        messages.success(
            self.request,
            "Contract created from proposal successfully.",
            extra_tags=_scope_tags("contract"),
        )

        if not self.proposal.deal.has_advance:
            messages.warning(
                self.request,
                "No advance payment is recorded for this deal yet.",
                extra_tags=_scope_tags("contract"),
            )

        return response

    def get_success_url(self):
        return reverse_lazy(
            "sales:contract_detail",
            kwargs={"pk": self.object.pk},
        )
    
class DealRecordAdvanceView(SalesAccessMixin, View):
    """
    Deal / accepted proposal -> Record Advance.

    Creates an advance invoice for the deal with a single "Booking advance"
    line and records the advance payment against it in one step. The
    contract invoice later deducts this amount.
    """

    template_name = "sales/advance_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.deal = get_object_or_404(
            Deal.objects.select_related("client", "lead"),
            pk=self.kwargs["pk"],
        )
        self.proposal = (
            self.deal.proposals.filter(status=ProposalStatus.ACCEPTED)
            .order_by("-updated_at")
            .first()
        )
        return super().dispatch(request, *args, **kwargs)

    def _render(self, request, form):
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "deal": self.deal,
                "proposal": self.proposal,
                "advance_paid": self.deal.advance_paid,
            },
        )

    def get(self, request, pk):
        initial = {"date": timezone.localdate()}

        total = self.proposal.total if self.proposal else self.deal.amount
        if total:
            initial["amount"] = percentage_amount(total, ADVANCE_PERCENT)

        return self._render(request, AdvancePaymentForm(initial=initial))

    @transaction.atomic
    def post(self, request, pk):
        form = AdvancePaymentForm(request.POST)
        if not form.is_valid():
            return self._render(request, form)

        data = form.cleaned_data
        amount = data["amount"]

        invoice = Invoice.objects.create(
            owner=request.user,
            deal=self.deal,
            is_advance=True,
            issue_date=data["date"],
            due_date=data["date"],
            status=InvoiceStatus.DRAFT,
            notes=data["notes"] or f"Booking advance for {self.deal.name}",
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description=(
                f"Booking advance - {self.proposal.title}"
                if self.proposal
                else "Booking advance"
            ),
            quantity=1,
            unit_price=amount,
        )

        invoice.status = InvoiceStatus.ISSUED
        invoice.save(update_fields=["status", "updated_at"])

        Payment.objects.create(
            owner=request.user,
            invoice=invoice,
            date=data["date"],
            amount=amount,
            payment_type=PaymentType.ADVANCE,
            method=data["method"],
            reference=data["reference"],
            notes=data["notes"],
            received_by=request.user,
        )

        if self.deal.stage in OPEN_DEAL_STAGES:
            self.deal.stage = DealStage.ADVANCE_RECEIVED
            self.deal.save(update_fields=["stage", "updated_at"])

        messages.success(
            request,
            f"Advance of {amount} recorded on invoice {invoice.number}. Next, create and send the contract.",
            extra_tags=_scope_tags("deal", "invoice"),
        )

        if self.proposal:
            return redirect("sales:proposal_detail", pk=self.proposal.pk)

        return redirect("sales:deal_detail", pk=self.deal.pk)


@method_decorator(require_POST, name="dispatch")
class ContractCreateClientEventView(SalesAccessMixin, View):
    """
    Last step of the sales flow:
    contract signed -> invoice generated -> Create Client & Event.

    Creates (or reuses) the client from the lead and one event per
    contract event day.
    """

    @transaction.atomic
    def post(self, request, pk):
        contract = get_object_or_404(
            Contract.objects.select_related("deal", "deal__client", "deal__lead"),
            pk=pk,
        )

        if contract.status != ContractStatus.SIGNED:
            messages.error(
                request,
                "The contract must be signed before creating the client and event.",
                extra_tags=_scope_tags("contract"),
            )
            return redirect("sales:contract_detail", pk=contract.pk)

        if not contract.invoices.exists():
            messages.error(
                request,
                "Please generate the invoice from this contract first.",
                extra_tags=_scope_tags("contract"),
            )
            return redirect("sales:contract_detail", pk=contract.pk)

        client, created_events, skipped_days = create_client_and_events_from_contract(
            contract,
            request.user,
        )

        if created_events:
            messages.success(
                request,
                f"Client {client} is ready and {len(created_events)} event(s) were created.",
                extra_tags=_scope_tags("client"),
            )
        else:
            messages.info(
                request,
                f"Client {client} is ready. No new events were created.",
                extra_tags=_scope_tags("client"),
            )

        if skipped_days:
            messages.warning(
                request,
                "No date found for: " + ", ".join(skipped_days) + ". Create those events manually.",
                extra_tags=_scope_tags("client"),
            )

        return redirect("crm:client_detail", pk=client.pk)


# ============================================================
# Contracts
# ============================================================

def _visible_contracts(qs, user):
    """
    Sales sees every contract. The rest of the company sees the digital
    copy of signed contracts only.
    """
    if can_access_sales(user):
        return qs
    return qs.filter(status=ContractStatus.SIGNED)


class ContractListView(ContractViewAccessMixin, ListView):
    model = Contract
    template_name = "sales/contract_list.html"
    context_object_name = "contracts"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("deal", "proposal", "deal__client", "owner")
            .prefetch_related("invoices")
        )
        qs = _visible_contracts(qs, self.request.user)

        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        deal_stage = (self.request.GET.get("deal_stage") or "").strip()

        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(deal__name__icontains=q)
                | Q(deal__client__name__icontains=q)
                | Q(deal__lead__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if deal_stage:
            qs = qs.filter(deal__stage=deal_stage)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = self.request.GET.get("q", "")
        context["filter_status"] = self.request.GET.get("status", "")
        context["filter_deal_stage"] = self.request.GET.get("deal_stage", "")
        context["status_choices"] = ContractStatus.choices
        context["deal_stage_choices"] = DealStage.choices

        return context


class ContractDetailView(ContractViewAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Contract
    template_name = "sales/contract_detail.html"
    context_object_name = "contract"
    detail_message_scope = "scope:contract"

    def get_queryset(self):
        return _visible_contracts(
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "proposal", "owner")
            .prefetch_related(
                "event_days",
                "event_days__items",
                "event_days__items__service",
                "event_days__items__package",
                "event_days__items__deliverables",
                "invoices",
            ),
            self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["pdf_download_url"] = reverse("sales:contract_download", args=[self.object.pk])
        context["has_invoice"] = _contract_has_invoice(self.object)
        context["invoice"] = self.object.invoices.order_by("-issue_date", "-created_at").first()

        return context






class ContractPDFDownloadView(ContractViewAccessMixin, DetailView):
    model = Contract

    def get_queryset(self):
        return _visible_contracts(
            super()
            .get_queryset()
            .select_related(
                "deal",
                "deal__client",
                "proposal",
                "proposal_plan",
                "owner",
            )
            .prefetch_related(
                "event_days",
                "event_days__items",
                "event_days__items__service",
                "event_days__items__package",
                "event_days__items__deliverables",
            ),
            self.request.user,
        )

    def get(self, request, *args, **kwargs):
        if HTML is None:
            raise Http404("PDF generation is not available. Install WeasyPrint.")

        contract = self.get_object()

        pdf_file = render_pdf(
            "sales/contract_pdf.html",
            build_contract_document_context(contract),
            request=request,
        )

        contract_id = _safe_filename_part(contract.number or contract.pk, f"contract-{contract.pk}")
        client_name = _client_filename_part(contract)
        filename = _pdf_filename(contract_id, client_name)

        response = HttpResponse(pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ContractDocumentView(ContractPDFDownloadView):
    """
    The digital contract in the browser: the same document as the PDF.
    """

    def get(self, request, *args, **kwargs):
        contract = self.get_object()
        context = build_contract_document_context(contract)
        context["screen"] = True
        return render(request, "sales/contract_pdf.html", context)


class ContractCreateView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    model = Contract
    form_class = ContractForm
    template_name = "sales/contract_form.html"

    def get_initial(self):
        initial = super().get_initial()

        deal_id = self.request.GET.get("deal")
        proposal_id = self.request.GET.get("proposal")

        if deal_id:
            initial["deal"] = deal_id

        if proposal_id:
            proposal = Proposal.objects.filter(pk=proposal_id).select_related("deal").first()

            if proposal:
                selected_plan = proposal.accepted_plan or proposal.get_pricing_plan()
                initial.update(
                    {
                        "deal": proposal.deal_id,
                        "proposal": proposal.pk,
                        "proposal_plan": selected_plan.pk if selected_plan else None,
                        "terms": proposal.terms,
                    }
                )

        return initial

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        contract = self.object

        if contract.proposal_id and not contract.event_days.exists():
            contract.populate_from_proposal(
                contract.proposal,
                plan=contract.proposal_plan,
                clear_existing=True,
            )

        messages.success(
            self.request,
            "Contract created successfully.",
            extra_tags=_scope_tags("contract"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:contract_detail", kwargs={"pk": self.object.pk})


class ContractUpdateView(SalesAccessMixin, OwnerAssignMixin, UpdateView):
    model = Contract
    form_class = ContractForm
    template_name = "sales/contract_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("deal", "proposal", "owner")

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        contract = self.object

        if contract.proposal_id and not contract.event_days.exists():
            contract.populate_from_proposal(
                contract.proposal,
                plan=contract.proposal_plan,
                clear_existing=True,
            )

        # Marked as signed by staff (e.g. a paper signature).
        if contract.status == ContractStatus.SIGNED:
            if not contract.signed_date:
                contract.signed_date = timezone.localdate()
                contract.save(update_fields=["signed_date", "updated_at"])
            if contract.deal.stage != DealStage.WON:
                mark_deal_won(contract.deal)

        messages.success(
            self.request,
            "Contract updated successfully.",
            extra_tags=_scope_tags("contract"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:contract_detail", kwargs={"pk": self.object.pk})

class ContractDeleteView(SalesAccessMixin, DeleteView):
    model = Contract
    template_name = "common/confirm_delete.html"
    success_url = reverse_lazy("sales:contract_list")

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "proposal", "owner")
        )

    def form_valid(self, form):
        messages.success(
            self.request,
            "Contract deleted successfully.",
            extra_tags=_scope_tags("contract"),
        )
        return super().form_valid(form)
    

class ContractGenerateInvoiceView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    """
    Contract detail page -> Generate Invoice.
    Creates invoice and copies contract items into invoice items.
    """

    model = Invoice
    form_class = InvoiceForm
    template_name = "sales/invoice_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.contract = get_object_or_404(
            Contract.objects.select_related("deal", "deal__client", "proposal"),
            pk=self.kwargs["pk"],
        )

        if self.contract.status != ContractStatus.SIGNED:
            messages.error(
                request,
                "The invoice can be generated once the contract is signed.",
                extra_tags=_scope_tags("invoice"),
            )
            return redirect("sales:contract_detail", pk=self.contract.pk)

        existing_invoice = self.contract.invoices.order_by("-issue_date", "-created_at").first()
        if existing_invoice:
            messages.info(
                request,
                "This contract already has an invoice.",
                extra_tags=_scope_tags("invoice"),
            )
            return redirect("sales:invoice_detail", pk=existing_invoice.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()

        today = timezone.localdate()

        initial.update(
            {
                "deal": self.contract.deal_id,
                "contract": self.contract.pk,
                "issue_date": today,
                "due_date": today + timedelta(days=7),
                "status": InvoiceStatus.DRAFT,
                "discount": self.contract.discount,
                "tax_rate": self.contract.tax_rate,
                "notes": f"Invoice generated from contract {self.contract.number}",
            }
        )

        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["source_contract"] = self.contract
        context["is_contract_conversion"] = True

        return context

    @transaction.atomic
    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user

        response = super().form_valid(form)

        self.object.populate_from_contract(self.contract, clear_existing=True)

        messages.success(
            self.request,
            "Invoice generated from contract successfully.",
            extra_tags=_scope_tags("invoice"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:invoice_detail", kwargs={"pk": self.object.pk})


# ============================================================
# Invoices
# ============================================================

class InvoiceListView(SalesAccessMixin, ListView):
    model = Invoice
    template_name = "sales/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def _get_period_dates(self, period_key):
        """
        Returns (start_date, end_date) for invoice issue_date filtering.
        """
        today = timezone.localdate()

        if period_key == "this_month":
            start = today.replace(day=1)
            end = today
            return start, end

        if period_key == "last_month":
            first_this_month = today.replace(day=1)
            last_previous_month = first_this_month - timedelta(days=1)
            start = last_previous_month.replace(day=1)
            end = last_previous_month
            return start, end

        if period_key == "last_3_months":
            first_this_month = today.replace(day=1)
            approx_two_months_back = first_this_month - timedelta(days=62)
            start = approx_two_months_back.replace(day=1)
            end = today
            return start, end

        if period_key == "last_year":
            start = date(today.year - 1, 1, 1)
            end = date(today.year - 1, 12, 31)
            return start, end

        return None, None

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "contract", "owner")
            .prefetch_related("payments")
        )

        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        period = (self.request.GET.get("period") or "").strip()

        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(deal__client__name__icontains=q)
                | Q(deal__lead__name__icontains=q)
                | Q(deal__client__display_name__icontains=q)
                | Q(deal__client__email__icontains=q)
                | Q(deal__client__phone__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        start_date, end_date = self._get_period_dates(period)
        if start_date and end_date:
            qs = qs.filter(issue_date__gte=start_date, issue_date__lte=end_date)

        return qs.order_by("-issue_date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = self.request.GET.get("q", "")
        context["filter_status"] = self.request.GET.get("status", "")
        context["filter_period"] = self.request.GET.get("period", "")

        context["status_choices"] = InvoiceStatus.choices
        context["period_choices"] = [
            ("", "All periods"),
            ("this_month", "This month"),
            ("last_month", "Last month"),
            ("last_3_months", "Last 3 months"),
            ("last_year", "Last year"),
        ]

        return context


class InvoiceDetailView(SalesReadOnlyAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Invoice
    template_name = "sales/invoice_detail.html"
    context_object_name = "invoice"
    detail_message_scope = "scope:invoice"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "contract", "owner")
            .prefetch_related(
                "items",
                "items__contract_item",
                "items__contract_item__service",
                "items__contract_item__package",
                "payments",
                "payments__received_by",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["pdf_download_url"] = reverse("sales:invoice_download", args=[self.object.pk])
        context["payments"] = self.object.payments.all().order_by("-date", "-created_at")
        context["client"] = self.object.deal.customer if self.object.deal_id else None

        return context


class InvoiceCreateView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "sales/invoice_form.html"

    def get_initial(self):
        initial = super().get_initial()

        deal_id = self.request.GET.get("deal")
        contract_id = self.request.GET.get("contract")
        today = timezone.localdate()

        if deal_id:
            initial["deal"] = deal_id

        if contract_id:
            contract = Contract.objects.filter(pk=contract_id).select_related("deal").first()

            if contract:
                initial.update(
                    {
                        "deal": contract.deal_id,
                        "contract": contract.pk,
                        "issue_date": today,
                        "due_date": today + timedelta(days=7),
                        "discount": contract.discount,
                        "tax_rate": contract.tax_rate,
                    }
                )
        else:
            initial.setdefault("issue_date", today)
            initial.setdefault("due_date", today + timedelta(days=7))

        return initial

    def _get_contract_for_invoice(self, invoice):
        contract_id = self.request.POST.get("contract") or self.request.GET.get("contract")

        if contract_id:
            return Contract.objects.filter(pk=contract_id, deal=invoice.deal).first()

        return invoice.deal.contracts.order_by("-signed_date", "-created_at").first()

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        contract = self._get_contract_for_invoice(self.object)

        if contract:
            self.object.populate_from_contract(contract, clear_existing=True)

        messages.success(
            self.request,
            "Invoice created successfully.",
            extra_tags=_scope_tags("invoice"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:invoice_detail", kwargs={"pk": self.object.pk})


class InvoiceUpdateView(SalesAccessMixin, OwnerAssignMixin, UpdateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "sales/invoice_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("deal", "contract", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)

        self.object.recalculate_totals(save=True)

        messages.success(
            self.request,
            "Invoice updated successfully.",
            extra_tags=_scope_tags("invoice"),
        )

        return response

    def get_success_url(self):
        return reverse_lazy("sales:invoice_detail", kwargs={"pk": self.object.pk})

class InvoiceDeleteView(SalesAccessMixin, DeleteView):
    model = Invoice
    template_name = "common/confirm_delete.html"
    success_url = reverse_lazy("sales:invoice_list")

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("deal", "deal__client", "contract", "owner")
            .prefetch_related("payments", "items")
        )

    def form_valid(self, form):
        messages.success(
            self.request,
            "Invoice deleted successfully.",
            extra_tags=_scope_tags("invoice"),
        )
        return super().form_valid(form)
    
class InvoicePDFDownloadView(SalesAccessMixin, DetailView):
    model = Invoice

    def get(self, request, *args, **kwargs):
        if HTML is None:
            raise Http404("PDF generation is not available. Install WeasyPrint.")

        invoice = self.get_object()

        pdf_file = render_pdf("sales/invoice_pdf.html", {"invoice": invoice}, request=request)

        invoice_id = _safe_filename_part(invoice.number or invoice.pk, f"invoice-{invoice.pk}")
        client_name = _client_filename_part(invoice)
        filename = _pdf_filename(invoice_id, client_name)

        response = HttpResponse(pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        return response


# ============================================================
# Payments
# ============================================================

class PaymentListView(SalesAccessMixin, ListView):
    model = Payment
    template_name = "sales/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related(
                "invoice",
                "invoice__deal",
                "invoice__deal__client",
                "received_by",
                "owner",
            )
        )

        q = (self.request.GET.get("q") or "").strip()
        method = (self.request.GET.get("method") or "").strip()
        payment_type = (self.request.GET.get("payment_type") or "").strip()

        if q:
            qs = qs.filter(
                Q(invoice__number__icontains=q)
                | Q(invoice__deal__client__name__icontains=q)
                | Q(invoice__deal__lead__name__icontains=q)
                | Q(invoice__deal__client__display_name__icontains=q)
                | Q(reference__icontains=q)
            )

        if method:
            qs = qs.filter(method=method)

        if payment_type:
            qs = qs.filter(payment_type=payment_type)

        return qs


class PaymentDetailView(SalesReadOnlyAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Payment
    template_name = "sales/payment_detail.html"
    context_object_name = "payment"
    detail_message_scope = "scope:payment"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "invoice",
                "invoice__deal",
                "invoice__deal__client",
                "received_by",
                "owner",
            )
        )


class PaymentCreateView(SalesAccessMixin, OwnerAssignMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "sales/payment_form.html"

    def get_initial(self):
        initial = super().get_initial()

        invoice_id = self.request.GET.get("invoice")
        if invoice_id:
            invoice = Invoice.objects.filter(pk=invoice_id).first()

            if invoice:
                initial.update(
                    {
                        "invoice": invoice.pk,
                        "date": timezone.localdate(),
                        "amount": invoice.balance,
                    }
                )

        return initial

    @transaction.atomic
    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user

        if not form.instance.received_by_id:
            form.instance.received_by = self.request.user

        response = super().form_valid(form)

        messages.success(
            self.request,
            "Payment added successfully.",
            extra_tags=_scope_tags("payment"),
        )

        return response

    def get_success_url(self):
        if self.object.invoice_id:
            return reverse_lazy("sales:invoice_detail", kwargs={"pk": self.object.invoice_id})

        return reverse_lazy("sales:payment_list")


class PaymentUpdateView(SalesAccessMixin, OwnerAssignMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "sales/payment_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("invoice", "received_by", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Payment updated successfully.",
            extra_tags=_scope_tags("payment"),
        )

        return response

    def get_success_url(self):
        if self.object.invoice_id:
            return reverse_lazy("sales:invoice_detail", kwargs={"pk": self.object.invoice_id})

        return reverse_lazy("sales:payment_list")

class PaymentDeleteView(SalesAccessMixin, DeleteView):
    model = Payment
    template_name = "common/confirm_delete.html"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "invoice",
                "invoice__deal",
                "invoice__deal__client",
                "received_by",
                "owner",
            )
        )

    def form_valid(self, form):
        messages.success(
            self.request,
            "Payment deleted successfully.",
            extra_tags=_scope_tags("payment"),
        )
        return super().form_valid(form)

    def get_success_url(self):
        if self.object.invoice_id:
            return reverse_lazy(
                "sales:invoice_detail",
                kwargs={"pk": self.object.invoice_id},
            )

        return reverse_lazy("sales:payment_list")
    
# ============================================================
# Send Email Actions
# ============================================================




@method_decorator(require_POST, name="dispatch")
class ProposalSendEmailView(SalesAccessMixin, View):
    def post(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("deal", "deal__client", "deal__lead"),
            pk=pk,
        )

        deal = proposal.deal
        client = deal.customer if deal else None
        contact = resolve_primary_contact(client)
        to_email = resolve_client_email(client)

        blocked = check_before_send(
            request,
            template_type=EmailTemplate.TemplateType.PROPOSAL,
            label="Proposal",
            to_email=to_email,
            redirect_url_name="sales:proposal_detail",
            redirect_pk=proposal.pk,
            object_scope="proposal",
            scope_tags=_scope_tags,
        )
        if blocked:
            return blocked

        context = build_common_email_context(
            client=client,
            contact=contact,
            deal=deal,
        )
        context.update({
            "proposal": proposal,
        })

        try:
            result = send_templated_email(
                template_type=EmailTemplate.TemplateType.PROPOSAL,
                to_emails=to_email,
                context=context,
            )
        except EmailSendError as exc:
            messages.error(
                request,
                f"Proposal email failed: {exc}",
                extra_tags=_scope_tags("proposal", "email"),
            )
            return redirect("sales:proposal_detail", pk=proposal.pk)

        if getattr(result, "ok", False):
            if proposal.status == ProposalStatus.DRAFT:
                proposal.status = ProposalStatus.SENT
                proposal.save(update_fields=["status", "updated_at"])

            if deal.stage in (DealStage.NEW, DealStage.QUALIFIED):
                deal.stage = DealStage.PROPOSAL_SENT
                deal.save(update_fields=["stage", "updated_at"])

        flash_send_result(
            request,
            label="Proposal",
            to_email=to_email,
            result=result,
            success_tags=_scope_tags("proposal", "email"),
        )

        return redirect("sales:proposal_detail", pk=proposal.pk)


@method_decorator(require_POST, name="dispatch")
class ContractSendEmailView(SalesAccessMixin, View):
    def post(self, request, pk):
        contract = get_object_or_404(
            Contract.objects.select_related(
                "deal",
                "deal__client",
                "proposal",
            ),
            pk=pk,
        )

        deal = contract.deal
        client = deal.customer if deal else None
        contact = resolve_primary_contact(client)
        to_email = resolve_client_email(client)

        blocked = check_before_send(
            request,
            template_type=EmailTemplate.TemplateType.CONTRACT,
            label="Contract",
            to_email=to_email,
            redirect_url_name="sales:contract_detail",
            redirect_pk=contract.pk,
            object_scope="contract",
            scope_tags=_scope_tags,
        )
        if blocked:
            return blocked

        # Make sure public signing token exists before creating the email link
        contract.ensure_signing_token()

        contract_signature_url = request.build_absolute_uri(
            contract.get_public_sign_path()
        )

        context = build_common_email_context(
            client=client,
            contact=contact,
            deal=deal,
        )

        context.update({
            "contract": contract,
            "proposal": contract.proposal,
            "contract_signature_url": contract_signature_url,
        })

        try:
            result = send_templated_email(
                template_type=EmailTemplate.TemplateType.CONTRACT,
                to_emails=to_email,
                context=context,
                related_object=contract,
            )
        except EmailSendError as exc:
            messages.error(
                request,
                f"Contract email failed: {exc}",
                extra_tags=_scope_tags("contract", "email"),
            )
            return redirect("sales:contract_detail", pk=contract.pk)

        if getattr(result, "ok", False):
            if contract.status != ContractStatus.SIGNED:
                contract.status = ContractStatus.PENDING_SIGNATURE
                contract.save(update_fields=["status", "updated_at"])

                deal.stage = DealStage.CONTRACT_SENT
                deal.save(update_fields=["stage", "updated_at"])

        flash_send_result(
            request,
            label="Contract",
            to_email=to_email,
            result=result,
            success_tags=_scope_tags("contract", "email"),
        )

        return redirect("sales:contract_detail", pk=contract.pk)


@method_decorator(require_POST, name="dispatch")
class InvoiceSendEmailView(SalesAccessMixin, View):
    def post(self, request, pk):
        invoice = get_object_or_404(
            Invoice.objects.select_related("deal", "deal__client", "contract"),
            pk=pk,
        )

        deal = invoice.deal
        client = deal.customer if deal else None
        contact = resolve_primary_contact(client)
        to_email = resolve_client_email(client)

        blocked = check_before_send(
            request,
            template_type=EmailTemplate.TemplateType.INVOICE,
            label="Invoice",
            to_email=to_email,
            redirect_url_name="sales:invoice_detail",
            redirect_pk=invoice.pk,
            object_scope="invoice",
            scope_tags=_scope_tags,
        )
        if blocked:
            return blocked

        context = build_common_email_context(
            client=client,
            contact=contact,
            deal=deal,
        )
        context.update({
            "invoice": invoice,
            "contract": invoice.contract,
        })

        try:
            result = send_templated_email(
                template_type=EmailTemplate.TemplateType.INVOICE,
                to_emails=to_email,
                context=context,
            )
        except EmailSendError as exc:
            messages.error(
                request,
                f"Invoice email failed: {exc}",
                extra_tags=_scope_tags("invoice", "email"),
            )
            return redirect("sales:invoice_detail", pk=invoice.pk)

        if getattr(result, "ok", False):
            if invoice.status == InvoiceStatus.DRAFT:
                invoice.status = InvoiceStatus.ISSUED
                invoice.save(update_fields=["status", "updated_at"])

        flash_send_result(
            request,
            label="Invoice",
            to_email=to_email,
            result=result,
            success_tags=_scope_tags("invoice", "email"),
        )

        return redirect("sales:invoice_detail", pk=invoice.pk)


@method_decorator(require_POST, name="dispatch")
class PaymentSendEmailView(SalesAccessMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(
            Payment.objects.select_related(
                "invoice",
                "invoice__deal",
                "invoice__deal__client",
                "received_by",
            ),
            pk=pk,
        )

        invoice = payment.invoice
        deal = invoice.deal if invoice else None
        client = deal.customer if deal else None
        contact = resolve_primary_contact(client)
        to_email = resolve_client_email(client)

        blocked = check_before_send(
            request,
            template_type=EmailTemplate.TemplateType.PAYMENT,
            label="Payment",
            to_email=to_email,
            redirect_url_name="sales:payment_detail",
            redirect_pk=payment.pk,
            object_scope="payment",
            scope_tags=_scope_tags,
        )
        if blocked:
            return blocked

        context = build_common_email_context(
            client=client,
            contact=contact,
            deal=deal,
        )
        context.update({
            "payment": payment,
            "invoice": invoice,
        })

        try:
            result = send_templated_email(
                template_type=EmailTemplate.TemplateType.PAYMENT,
                to_emails=to_email,
                context=context,
            )
        except EmailSendError as exc:
            messages.error(
                request,
                f"Payment email failed: {exc}",
                extra_tags=_scope_tags("payment", "email"),
            )
            return redirect("sales:payment_detail", pk=payment.pk)

        flash_send_result(
            request,
            label="Payment",
            to_email=to_email,
            result=result,
            success_tags=_scope_tags("payment", "email"),
        )

        return redirect("sales:payment_detail", pk=payment.pk)
    
def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")






class ContractPublicSignView(View):
    template_name = "sales/contract_public_sign.html"

    def get_contract(self, token):
        return get_object_or_404(
            Contract.objects.select_related(
                "deal",
                "deal__client",
                "deal__lead",
                "proposal",
                "proposal_plan",
            ).prefetch_related(
                "event_days",
                "event_days__items",
                "event_days__items__service",
                "event_days__items__package",
                "event_days__items__deliverables",
            ),
            signing_token=token,
        )

    def get_context_data(self, contract):
        client = contract.deal.customer if contract.deal else None

        total_amount = get_contract_public_sign_total(contract)

        booking_advance = percentage_amount(total_amount, ADVANCE_PERCENT)
        on_event_amount = percentage_amount(total_amount, EVENT_PERCENT)
        after_delivery_amount = total_amount - booking_advance - on_event_amount
        balance_amount = total_amount - booking_advance

        return {
            "contract": contract,
            "client": client,
            "event_days": contract.event_days.all(),
            "already_signed": contract.status == ContractStatus.SIGNED,

            "total_amount": total_amount,
            "booking_advance": booking_advance,
            "balance_amount": balance_amount,
            "on_event_amount": on_event_amount,
            "after_delivery_amount": after_delivery_amount,

            "advance_percent": ADVANCE_PERCENT,
            "event_percent": EVENT_PERCENT,
            "delivery_percent": DELIVERY_PERCENT,

            "client_notes": get_payment_plan_client_notes(),
            "terms": get_payment_plan_terms(),
            "important_terms": get_payment_plan_important_terms(),
        }

    def get(self, request, token):
        contract = self.get_contract(token)

        if contract.status == ContractStatus.CANCELLED:
            return render(
                request,
                "sales/contract_sign_unavailable.html",
                {
                    "title": "Contract unavailable",
                    "message": "This contract is no longer available for signing.",
                    "contract": contract,
                },
                status=403,
            )

        return render(
            request,
            self.template_name,
            self.get_context_data(contract),
        )

    def post(self, request, token):
        contract = self.get_contract(token)

        if contract.status == ContractStatus.CANCELLED:
            messages.error(
                request,
                "This contract is no longer available for signing.",
                extra_tags=_scope_tags("contract", "public"),
            )
            return redirect("sales:contract_public_sign", token=token)

        if contract.status == ContractStatus.SIGNED:
            messages.info(
                request,
                "This contract has already been signed.",
                extra_tags=_scope_tags("contract", "public"),
            )
            return redirect("sales:contract_public_sign", token=token)

        signed_by_name = (request.POST.get("signed_by_name") or "").strip()
        accepted_terms = request.POST.get("accepted_terms") == "on"

        if not signed_by_name:
            messages.error(
                request,
                "Please enter your full name before signing.",
                extra_tags=_scope_tags("contract", "public"),
            )
            return redirect("sales:contract_public_sign", token=token)

        if not accepted_terms:
            messages.error(
                request,
                "Please confirm that you have read and accepted the contract terms and payment conditions.",
                extra_tags=_scope_tags("contract", "public"),
            )
            return redirect("sales:contract_public_sign", token=token)

        contract.status = ContractStatus.SIGNED
        contract.signed_date = timezone.localdate()
        contract.signed_at = timezone.now()
        contract.signed_by_name = signed_by_name
        contract.signed_ip_address = get_client_ip(request)
        contract.signed_user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]

        contract.save(
            update_fields=[
                "status",
                "signed_date",
                "signed_at",
                "signed_by_name",
                "signed_ip_address",
                "signed_user_agent",
                "updated_at",
            ]
        )

        mark_deal_won(contract.deal)

        messages.success(
            request,
            "Contract signed successfully. Thank you.",
            extra_tags=_scope_tags("contract", "public"),
        )

        return redirect("sales:contract_public_sign", token=token)
