# crm/views.py
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView

from .forms import ClientForm, ContactForm, InquiryForm, LeadForm, ReviewForm
from .models import Client, Contact, Inquiry, Lead, Review
from sales.models import Payment

from common.mixins import (
    AdminCRMManagerMixin,
    InquiryManagerMixin,
    KeepPaymentsOnDeleteMixin,
    StaffAllMixin,
    SalesReadOnlyAccessMixin,
)


# ============================================================
# Shared helpers
# ============================================================

class OwnerAssignMixin:
    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user
        return super().form_valid(form)


def _scope_tags(*scopes):
    """
    Usage:
        _scope_tags("client")
        returns: "scope:client"

        _scope_tags("proposal", "client")
        returns: "scope:proposal scope:client"

    Also accepts already-prefixed values:
        _scope_tags("scope:client")
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


class CommonDeleteMixin:
    """Use one shared delete confirmation template for all CRM objects."""

    template_name = "common/confirm_delete.html"
    object_type = "object"
    object_scope = "object"
    cancel_url_name = None
    success_url_name = None
    warning_message = "This action cannot be undone."

    def get_cancel_url(self):
        if self.cancel_url_name:
            return reverse(self.cancel_url_name, kwargs={"pk": self.object.pk})
        return self.get_success_url()

    def get_object_label(self):
        return str(self.object)

    def get_related_counts(self):
        return []

    def get_message_tags(self):
        return _scope_tags(self.object_scope or self.object_type)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "object_type": self.object_type,
                "object_label": self.get_object_label(),
                "cancel_url": self.get_cancel_url(),
                "warning_message": self.warning_message,
                "related_counts": self.get_related_counts(),
            }
        )
        return context

    def form_valid(self, form):
        object_label = self.get_object_label()
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"{self.object_type.title()} '{object_label}' deleted successfully.",
            extra_tags=self.get_message_tags(),
        )
        return response


# ============================================================
# Reviews: Admin + CRM Manager
# ============================================================

class ReviewListView(AdminCRMManagerMixin, ListView):
    model = Review
    template_name = "crm/review_list.html"
    context_object_name = "reviews"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("client", "owner")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(comment__icontains=q)
                | Q(client__name__icontains=q)
                | Q(client__display_name__icontains=q)
                | Q(next_action__icontains=q)
            )
        client_id = (self.request.GET.get("client") or "").strip()
        if client_id:
            qs = qs.filter(client_id=client_id)
        rating = (self.request.GET.get("rating") or "").strip()
        if rating.isdigit():
            qs = qs.filter(rating=int(rating))
        action_due = (self.request.GET.get("action_due") or "").strip()
        if action_due:
            today = timezone.localdate()
            if action_due == "overdue":
                qs = qs.filter(next_action_date__lt=today)
            elif action_due == "today":
                qs = qs.filter(next_action_date=today)
            elif action_due == "upcoming":
                qs = qs.filter(next_action_date__gt=today)
            elif action_due == "no_date":
                qs = qs.filter(next_action_date__isnull=True)
        return qs


class ReviewDetailView(AdminCRMManagerMixin, DetailView):
    model = Review
    template_name = "crm/review_detail.html"
    context_object_name = "review"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "owner")


class ReviewCreateView(AdminCRMManagerMixin, OwnerAssignMixin, CreateView):
    model = Review
    form_class = ReviewForm
    template_name = "crm/review_form.html"

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("client"):
            initial["client"] = self.request.GET.get("client")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Review created successfully.",
            extra_tags=_scope_tags("review", "client") if self.object.client_id else _scope_tags("review"),
        )
        return response

    def get_success_url(self):
        if self.object.client_id:
            return reverse("crm:client_detail", kwargs={"pk": self.object.client_id}) + "#tab-reviews"
        return reverse_lazy("crm:review_list")


class ReviewUpdateView(AdminCRMManagerMixin, OwnerAssignMixin, UpdateView):
    model = Review
    form_class = ReviewForm
    template_name = "crm/review_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Review updated successfully.",
            extra_tags=_scope_tags("review", "client") if self.object.client_id else _scope_tags("review"),
        )
        return response

    def get_success_url(self):
        if self.object.client_id:
            return reverse("crm:client_detail", kwargs={"pk": self.object.client_id}) + "#tab-reviews"
        return reverse_lazy("crm:review_list")


class ReviewDeleteView(AdminCRMManagerMixin, CommonDeleteMixin, DeleteView):
    model = Review
    context_object_name = "review"
    object_type = "review"
    object_scope = "review"
    cancel_url_name = "crm:review_detail"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "owner")

    def get_message_tags(self):
        if self.object.client_id:
            return _scope_tags("review", "client")
        return _scope_tags("review")

    def get_success_url(self):
        if self.object.client_id:
            return reverse("crm:client_detail", kwargs={"pk": self.object.client_id}) + "#tab-reviews"
        return reverse_lazy("crm:review_list")


# ============================================================
# Contacts: Admin + CRM Manager
# ============================================================

class ContactListView(AdminCRMManagerMixin, ListView):
    model = Contact
    template_name = "crm/contact_list.html"
    context_object_name = "contacts"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("client", "owner")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(whatsapp__icontains=q)
                | Q(client__name__icontains=q)
                | Q(client__display_name__icontains=q)
            )
        role = (self.request.GET.get("role") or "").strip()
        if role:
            qs = qs.filter(role=role)
        is_primary = (self.request.GET.get("is_primary") or "").strip()
        if is_primary == "1":
            qs = qs.filter(is_primary=True)
        elif is_primary == "0":
            qs = qs.filter(is_primary=False)
        return qs


class ContactDetailView(AdminCRMManagerMixin, DetailView):
    model = Contact
    template_name = "crm/contact_detail.html"
    context_object_name = "contact"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "owner")


class ContactCreateView(AdminCRMManagerMixin, OwnerAssignMixin, CreateView):
    model = Contact
    form_class = ContactForm
    template_name = "crm/contact_form.html"

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("client"):
            initial["client"] = self.request.GET.get("client")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Contact created successfully.",
            extra_tags=_scope_tags("contact", "client") if self.object.client_id else _scope_tags("contact"),
        )
        return response

    def get_success_url(self):
        if self.object.client_id:
            return reverse("crm:client_detail", kwargs={"pk": self.object.client_id}) + "#tab-contacts"
        return reverse_lazy("crm:contact_list")


class ContactUpdateView(AdminCRMManagerMixin, OwnerAssignMixin, UpdateView):
    model = Contact
    form_class = ContactForm
    template_name = "crm/contact_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Contact updated successfully.",
            extra_tags=_scope_tags("contact", "client") if self.object.client_id else _scope_tags("contact"),
        )
        return response

    def get_success_url(self):
        if self.object.client_id:
            return reverse("crm:client_detail", kwargs={"pk": self.object.client_id}) + "#tab-contacts"
        return reverse_lazy("crm:contact_list")


class ContactDeleteView(AdminCRMManagerMixin, CommonDeleteMixin, DeleteView):
    model = Contact
    context_object_name = "contact"
    object_type = "contact"
    object_scope = "contact"
    cancel_url_name = "crm:contact_detail"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "owner")

    def get_object_label(self):
        return f"{self.object.first_name} {self.object.last_name}".strip()

    def get_message_tags(self):
        if self.object.client_id:
            return _scope_tags("contact", "client")
        return _scope_tags("contact")

    def get_success_url(self):
        if self.object.client_id:
            return reverse("crm:client_detail", kwargs={"pk": self.object.client_id}) + "#tab-contacts"
        return reverse_lazy("crm:contact_list")


# ============================================================
# Clients: Admin + CRM Manager
# ============================================================

class ClientListView(AdminCRMManagerMixin, ListView):
    model = Client
    template_name = "crm/client_list.html"
    context_object_name = "clients"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("owner").annotate(
            deal_count=Count("deals", distinct=True),
            event_count=Count("events", distinct=True),
        ).order_by("name")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(display_name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(city__icontains=q)
                | Q(district__icontains=q)
                | Q(state__icontains=q)
                | Q(country__icontains=q)
            )
        is_active = (self.request.GET.get("is_active") or "").strip()
        if is_active == "1":
            qs = qs.filter(is_active=True)
        elif is_active == "0":
            qs = qs.filter(is_active=False)
        district = (self.request.GET.get("district") or "").strip()
        if district:
            qs = qs.filter(district__icontains=district)
        country = (self.request.GET.get("country") or "").strip()
        if country:
            qs = qs.filter(country__iexact=country)
        return qs


class ClientDetailView(SalesReadOnlyAccessMixin, DetailView):
    model = Client
    template_name = "crm/client_detail.html"
    context_object_name = "client"

    def get_queryset(self):
        return (
            super().get_queryset().select_related("owner").prefetch_related(
                "contacts", "leads", "reviews", "inquiries", "deals",
                "deals__proposals", "deals__contracts", "deals__invoices",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = self.object
        contacts = list(client.contacts.all())
        reviews = list(client.reviews.all())
        ratings = [r.rating for r in reviews if r.rating is not None]
        context.update({
            "contacts": sorted(contacts, key=lambda c: (not c.is_primary, c.first_name.lower())),
            "reviews": reviews,
            "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "deals": client.deals.all().order_by("-created_at"),
            "events": client.events.select_related("venue").order_by("date", "start_time"),
            "projects": client.projects.select_related("manager").order_by("-created_at"),
            "leads": client.leads.all(),
            "inquiries": client.inquiries.all(),
        })
        return context


class ClientCreateView(AdminCRMManagerMixin, OwnerAssignMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "crm/client_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Client created successfully.",
            extra_tags=_scope_tags("client"),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("crm:client_detail", kwargs={"pk": self.object.pk})


class ClientUpdateView(AdminCRMManagerMixin, OwnerAssignMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = "crm/client_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("owner")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Client updated successfully.",
            extra_tags=_scope_tags("client"),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("crm:client_detail", kwargs={"pk": self.object.pk})


class ClientDeleteView(AdminCRMManagerMixin, KeepPaymentsOnDeleteMixin, CommonDeleteMixin, DeleteView):
    model = Client
    context_object_name = "client"
    object_type = "client"
    object_scope = "client"
    cancel_url_name = "crm:client_detail"
    success_url = reverse_lazy("crm:client_list")
    warning_message = (
        "This may also delete related contacts, reviews, inquiries, leads, deals, "
        "proposals, contracts, invoices and payments depending on your model relationships."
    )

    def get_queryset(self):
        return super().get_queryset().select_related("owner").prefetch_related(
            "contacts", "reviews", "inquiries", "leads", "deals"
        )

    def get_object_label(self):
        return self.object.display_name or self.object.name

    def get_blocking_payments(self):
        return Payment.objects.filter(invoice__deal__client=self.object)

    def get_blocked_redirect_url(self):
        return reverse("crm:client_detail", kwargs={"pk": self.object.pk})

    def get_related_counts(self):
        return [
            ("Contacts", self.object.contacts.count()),
            ("Reviews", self.object.reviews.count()),
            ("Inquiries", self.object.inquiries.count()),
            ("Leads", self.object.leads.count()),
            ("Deals", self.object.deals.count() if hasattr(self.object, "deals") else 0),
        ]


# ============================================================
# Leads: Admin + CRM Manager
# ============================================================

class LeadListView(AdminCRMManagerMixin, ListView):
    model = Lead
    template_name = "crm/lead_list.html"
    context_object_name = "leads"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("client", "inquiry", "owner")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(whatsapp__icontains=q)
                | Q(wedding_city__icontains=q)
                | Q(wedding_district__icontains=q)
                | Q(client__name__icontains=q)
                | Q(client__display_name__icontains=q)
                | Q(notes__icontains=q)
            )
        status = (self.request.GET.get("status") or "").strip()
        if status:
            qs = qs.filter(status=status)
        source = (self.request.GET.get("source") or "").strip()
        if source:
            qs = qs.filter(source=source)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Lead._meta.get_field("status").choices
        context["source_choices"] = Lead._meta.get_field("source").choices
        return context


class LeadDetailView(AdminCRMManagerMixin, DetailView):
    model = Lead
    template_name = "crm/lead_detail.html"
    context_object_name = "lead"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "client", "inquiry", "owner"
        ).prefetch_related(
            "source_inquiries", "deals", "deals__proposals"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["deals"] = self.object.deals.all().order_by("-created_at") if hasattr(self.object, "deals") else []
        return context


class LeadCreateView(AdminCRMManagerMixin, OwnerAssignMixin, CreateView):
    model = Lead
    form_class = LeadForm
    template_name = "crm/lead_form.html"

    def get_initial(self):
        initial = super().get_initial()
        inquiry_id = self.request.GET.get("inquiry")
        if inquiry_id:
            inquiry = Inquiry.objects.filter(pk=inquiry_id).first()
            if inquiry:
                initial.update(_lead_initial_from_inquiry(inquiry))
        return initial

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        inquiry = form.cleaned_data.get("inquiry")
        if inquiry:
            inquiry.lead = self.object
            inquiry.status = Inquiry.STATUS_CONVERTED_TO_LEAD
            inquiry.save(update_fields=["lead", "status", "updated_at"])
            messages.success(
                self.request,
                "Lead created successfully and linked to the inquiry.",
                extra_tags=_scope_tags("lead", "inquiry"),
            )
        else:
            messages.success(
                self.request,
                "Lead created successfully.",
                extra_tags=_scope_tags("lead"),
            )
        return response

    def get_success_url(self):
        return reverse_lazy("crm:lead_detail", kwargs={"pk": self.object.pk})


class LeadUpdateView(AdminCRMManagerMixin, OwnerAssignMixin, UpdateView):
    model = Lead
    form_class = LeadForm
    template_name = "crm/lead_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("client", "inquiry", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Lead updated successfully.",
            extra_tags=_scope_tags("lead"),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("crm:lead_detail", kwargs={"pk": self.object.pk})


class LeadDeleteView(AdminCRMManagerMixin, CommonDeleteMixin, DeleteView):
    model = Lead
    context_object_name = "lead"
    object_type = "lead"
    object_scope = "lead"
    cancel_url_name = "crm:lead_detail"
    warning_message = "This may also affect related inquiries and deals depending on your model relationships."

    def get_queryset(self):
        return super().get_queryset().select_related("client", "inquiry", "owner").prefetch_related("source_inquiries", "deals")

    def get_object_label(self):
        return self.object.name

    def get_message_tags(self):
        if self.object.client_id:
            return _scope_tags("lead", "client")
        return _scope_tags("lead")

    def get_success_url(self):
        if self.object.client_id:
            return reverse_lazy("crm:client_detail", kwargs={"pk": self.object.client_id})
        return reverse_lazy("crm:lead_list")

    def get_related_counts(self):
        return [
            ("Source inquiries", self.object.source_inquiries.count()),
            ("Deals", self.object.deals.count() if hasattr(self.object, "deals") else 0),
        ]


# ============================================================
# Inquiries
# List/detail/create: all staff
# Update/delete: InquiryManagerMixin
# Convert: Admin + CRM Manager
# ============================================================

class InquiryListView(StaffAllMixin, ListView):
    model = Inquiry
    template_name = "crm/inquiry_list.html"
    context_object_name = "inquiries"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("lead", "client", "handled_by", "owner")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(whatsapp__icontains=q)
                | Q(message__icontains=q)
                | Q(client__name__icontains=q)
                | Q(client__display_name__icontains=q)
                | Q(handled_by__first_name__icontains=q)
                | Q(handled_by__last_name__icontains=q)
                | Q(handled_by__username__icontains=q)
            )
        status = (self.request.GET.get("status") or "").strip()
        if status:
            qs = qs.filter(status=status)
        channel = (self.request.GET.get("channel") or "").strip()
        if channel:
            qs = qs.filter(channel=channel)
        handled_by = (self.request.GET.get("handled_by") or "").strip()
        if handled_by:
            qs = qs.filter(handled_by_id=handled_by)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Inquiry._meta.get_field("status").choices
        context["channel_choices"] = Inquiry._meta.get_field("channel").choices
        return context


class InquiryDetailView(StaffAllMixin, DetailView):
    model = Inquiry
    template_name = "crm/inquiry_detail.html"
    context_object_name = "inquiry"

    def get_queryset(self):
        return super().get_queryset().select_related("lead", "client", "handled_by", "owner")


class InquiryCreateView(StaffAllMixin, OwnerAssignMixin, CreateView):
    model = Inquiry
    form_class = InquiryForm
    template_name = "crm/inquiry_form.html"
    success_url = reverse_lazy("crm:inquiry_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Inquiry created successfully.",
            extra_tags=_scope_tags("inquiry"),
        )
        return response


class InquiryUpdateView(InquiryManagerMixin, OwnerAssignMixin, UpdateView):
    model = Inquiry
    form_class = InquiryForm
    template_name = "crm/inquiry_form.html"

    def get_queryset(self):
        return super().get_queryset().select_related("lead", "client", "handled_by", "owner")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Inquiry updated successfully.",
            extra_tags=_scope_tags("inquiry"),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("crm:inquiry_detail", kwargs={"pk": self.object.pk})


class InquiryDeleteView(InquiryManagerMixin, CommonDeleteMixin, DeleteView):
    model = Inquiry
    context_object_name = "inquiry"
    object_type = "inquiry"
    object_scope = "inquiry"
    cancel_url_name = "crm:inquiry_detail"
    success_url = reverse_lazy("crm:inquiry_list")
    warning_message = "This will remove the inquiry record. Existing linked lead/client records will not be deleted if their foreign keys use SET_NULL."

    def get_queryset(self):
        return super().get_queryset().select_related("lead", "client", "handled_by", "owner")

    def get_object_label(self):
        return self.object.name or self.object.email or self.object.phone or self.object.whatsapp or f"Inquiry #{self.object.pk}"

    def get_related_counts(self):
        return [
            ("Linked lead", 1 if self.object.lead_id else 0),
            ("Linked client", 1 if self.object.client_id else 0),
        ]


class InquiryConvertToLeadView(AdminCRMManagerMixin, OwnerAssignMixin, CreateView):
    model = Lead
    form_class = LeadForm
    template_name = "crm/lead_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.inquiry = get_object_or_404(
            Inquiry.objects.select_related("client", "lead", "owner", "handled_by"),
            pk=self.kwargs["pk"],
        )
        if self.inquiry.lead_id:
            messages.info(
                request,
                "This inquiry is already converted to a lead.",
                extra_tags=_scope_tags("inquiry", "lead"),
            )
            return redirect("crm:lead_detail", pk=self.inquiry.lead_id)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial.update(_lead_initial_from_inquiry(self.inquiry))
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["source_inquiry"] = self.inquiry
        context["is_conversion"] = True
        return context

    @transaction.atomic
    def form_valid(self, form):
        if hasattr(form.instance, "owner") and not form.instance.owner_id:
            form.instance.owner = self.request.user
        response = super().form_valid(form)

        self.inquiry.lead = self.object
        self.inquiry.status = Inquiry.STATUS_CONVERTED_TO_LEAD
        self.inquiry.save(update_fields=["lead", "status", "updated_at"])

        messages.success(
            self.request,
            "Inquiry converted to lead successfully.",
            extra_tags=_scope_tags("inquiry", "lead"),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("crm:lead_detail", kwargs={"pk": self.object.pk})


def _lead_initial_from_inquiry(inquiry):
    return {
        "inquiry": inquiry.pk,
        "client": inquiry.client_id,
        "name": inquiry.name or inquiry.email or inquiry.phone or inquiry.whatsapp or "New Lead",
        "email": inquiry.email,
        "phone": inquiry.phone,
        "whatsapp": inquiry.whatsapp,
        "wedding_date": inquiry.wedding_date,
        "wedding_city": inquiry.wedding_city,
        "wedding_district": inquiry.wedding_district,
        "wedding_state": inquiry.wedding_state,
        "wedding_country": inquiry.wedding_country,
        "source": inquiry.channel,
        "source_detail": f"Converted from inquiry #{inquiry.pk}",
        "notes": inquiry.message,
        "status": Lead.STATUS_NEW,
    }
