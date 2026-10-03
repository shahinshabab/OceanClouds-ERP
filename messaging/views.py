from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from common.mixins import SalesAccessMixin
from common.roles import (
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_EMPLOYEE,
    ROLE_MANAGER,
    ROLE_PROJECT_MANAGER,
    user_has_role,
)

from .forms import CampaignForm, EmailTemplateForm, TicketForm, WhatsAppTemplateForm
from .models import (
    Campaign,
    CampaignRecipient,
    EmailSendLog,
    EmailTemplate,
    Ticket,
    TicketPriority,
    TicketStatus,
    WhatsAppSendLog,
    WhatsAppTemplate,
)
from .services import sync_campaign_recipients
from .utils import render_email_from_template, render_template_string


class MessagingAccessMixin(SalesAccessMixin):
    """
    Messaging belongs with CRM/Sales:
    Admin + CRM Manager.
    """
    pass


class EmailTemplateListView(MessagingAccessMixin, ListView):
    model = EmailTemplate
    template_name = "messaging/emailtemplate_list.html"
    context_object_name = "templates"
    paginate_by = 20

    def get_queryset(self):
        qs = EmailTemplate.objects.all()

        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(slug__icontains=q)
                | Q(subject__icontains=q)
            )

        template_type = self.request.GET.get("type") or ""
        if template_type:
            qs = qs.filter(type=template_type)

        is_active = self.request.GET.get("is_active") or ""
        if is_active == "1":
            qs = qs.filter(is_active=True)
        elif is_active == "0":
            qs = qs.filter(is_active=False)

        return qs.select_related("owner")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type_choices"] = EmailTemplate.TemplateType.choices
        context["current_q"] = self.request.GET.get("q") or ""
        context["current_type"] = self.request.GET.get("type") or ""
        context["current_is_active"] = self.request.GET.get("is_active") or ""
        return context


class EmailTemplateDetailView(MessagingAccessMixin, DetailView):
    model = EmailTemplate
    template_name = "messaging/emailtemplate_detail.html"
    context_object_name = "template"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["attachments"] = self.object.attachments.all()
        context["logs"] = self.object.send_logs.all()[:10]
        return context


class EmailTemplateCreateView(MessagingAccessMixin, CreateView):
    model = EmailTemplate
    form_class = EmailTemplateForm
    template_name = "messaging/emailtemplate_form.html"

    @transaction.atomic
    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user

        response = super().form_valid(form)

        if self.object.is_active:
            EmailTemplate.objects.filter(
                type=self.object.type,
                is_active=True,
            ).exclude(pk=self.object.pk).update(
                is_active=False,
                is_default_for_type=False,
            )

        messages.success(self.request, "Email template saved.")
        return response

    def get_success_url(self):
        return reverse("messaging:template_detail", args=[self.object.pk])


class EmailTemplateUpdateView(MessagingAccessMixin, UpdateView):
    model = EmailTemplate
    form_class = EmailTemplateForm
    template_name = "messaging/emailtemplate_form.html"

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        if self.object.is_active:
            EmailTemplate.objects.filter(
                type=self.object.type,
                is_active=True,
            ).exclude(pk=self.object.pk).update(
                is_active=False,
                is_default_for_type=False,
            )

        messages.success(self.request, "Email template updated.")
        return response

    def get_success_url(self):
        return reverse("messaging:template_detail", args=[self.object.pk])


class EmailTemplateDeleteView(MessagingAccessMixin, DeleteView):
    model = EmailTemplate
    template_name = "messaging/emailtemplate_confirm_delete.html"
    success_url = reverse_lazy("messaging:template_list")

    def post(self, request, *args, **kwargs):
        messages.success(request, "Email template deleted.")
        return super().post(request, *args, **kwargs)


class EmailTemplatePreviewView(MessagingAccessMixin, DetailView):
    model = EmailTemplate
    template_name = "messaging/emailtemplate_preview.html"
    context_object_name = "template"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        sample_context = {
            "company_name": "Ocean Clouds",
            "client": {
                "name": "Sample Client",
                "display_name": "Sample Client",
            },
            "contact": {
                "first_name": "Bride",
                "last_name": "Name",
                "email": "bride@example.com",
            },
            "proposal": {
                "title": "Wedding Photography Proposal",
                "total_amount": "45000",
            },
            "contract": {
                "title": "Wedding Photography Contract",
                "status": "Draft",
            },
            "invoice": {
                "invoice_number": "INV-1001",
                "total_amount": "45000",
                "due_date": "2026-05-30",
            },
            "payment": {
                "amount": "10000",
                "payment_date": "2026-05-07",
            },
            "today": "2026-05-07",
        }

        subject, html, text = render_email_from_template(
            self.object,
            sample_context,
        )

        context["preview_subject"] = subject
        context["preview_html"] = html
        context["preview_text"] = text
        context["sample_variables"] = sample_context
        context["back_url"] = reverse("messaging:template_detail", args=[self.object.pk])

        return context


class CampaignListView(MessagingAccessMixin, ListView):
    model = Campaign
    template_name = "messaging/campaign_list.html"
    context_object_name = "campaigns"
    paginate_by = 20

    def get_queryset(self):
        qs = Campaign.objects.select_related("template", "owner")

        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(description__icontains=q)
            )

        status = self.request.GET.get("status") or ""
        if status:
            qs = qs.filter(status=status)

        target_type = self.request.GET.get("target_type") or ""
        if target_type:
            qs = qs.filter(target_type=target_type)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Campaign.Status.choices
        context["target_type_choices"] = Campaign.TargetType.choices
        context["current_q"] = self.request.GET.get("q") or ""
        context["current_status"] = self.request.GET.get("status") or ""
        context["current_target_type"] = self.request.GET.get("target_type") or ""
        return context


class CampaignDetailView(MessagingAccessMixin, DetailView):
    model = Campaign
    template_name = "messaging/campaign_detail.html"
    context_object_name = "campaign"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        recipients = self.object.recipients.all()

        context["sent_count"] = recipients.filter(status=CampaignRecipient.SendStatus.SENT).count()
        context["pending_count"] = recipients.filter(status=CampaignRecipient.SendStatus.PENDING).count()
        context["failed_count"] = recipients.filter(status=CampaignRecipient.SendStatus.FAILED).count()
        context["skipped_count"] = recipients.filter(status=CampaignRecipient.SendStatus.SKIPPED).count()
        context["total_recipients"] = recipients.count()
        context["recipients"] = recipients.order_by("status", "email")[:25]

        return context


class CampaignCreateView(MessagingAccessMixin, CreateView):
    model = Campaign
    form_class = CampaignForm
    template_name = "messaging/campaign_form.html"

    @transaction.atomic
    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user

        response = super().form_valid(form)

        sync_campaign_recipients(self.object)

        messages.success(self.request, "Campaign created and recipients synced.")
        return response

    def get_success_url(self):
        return reverse("messaging:campaign_detail", args=[self.object.pk])


class CampaignUpdateView(MessagingAccessMixin, UpdateView):
    model = Campaign
    form_class = CampaignForm
    template_name = "messaging/campaign_form.html"

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        sync_campaign_recipients(self.object)

        messages.success(self.request, "Campaign updated and recipients synced.")
        return response

    def get_success_url(self):
        return reverse("messaging:campaign_detail", args=[self.object.pk])


class CampaignDeleteView(MessagingAccessMixin, DeleteView):
    model = Campaign
    template_name = "messaging/campaign_confirm_delete.html"
    success_url = reverse_lazy("messaging:campaign_list")

    def post(self, request, *args, **kwargs):
        messages.success(request, "Campaign deleted.")
        return super().post(request, *args, **kwargs)


class CampaignPauseView(MessagingAccessMixin, DetailView):
    model = Campaign

    def post(self, request, *args, **kwargs):
        campaign = self.get_object()
        campaign.status = Campaign.Status.PAUSED
        campaign.save(update_fields=["status"])

        messages.info(request, f"Campaign '{campaign.name}' paused.")
        return redirect("messaging:campaign_detail", pk=campaign.pk)


class CampaignResumeView(MessagingAccessMixin, DetailView):
    model = Campaign

    def post(self, request, *args, **kwargs):
        campaign = self.get_object()
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save(update_fields=["status"])

        messages.success(request, f"Campaign '{campaign.name}' resumed.")
        return redirect("messaging:campaign_detail", pk=campaign.pk)


class EmailSendLogListView(MessagingAccessMixin, ListView):
    model = EmailSendLog
    template_name = "messaging/email_log_list.html"
    context_object_name = "logs"
    paginate_by = 30

    def get_queryset(self):
        qs = EmailSendLog.objects.select_related("template")

        status = self.request.GET.get("status") or ""
        if status:
            qs = qs.filter(status=status)

        template_type = self.request.GET.get("type") or ""
        if template_type:
            qs = qs.filter(template_type=template_type)

        return qs
    
class WhatsAppTemplateListView(MessagingAccessMixin, ListView):
    model = WhatsAppTemplate
    template_name = "messaging/whatsapptemplate_list.html"
    context_object_name = "templates"
    paginate_by = 20

    def get_queryset(self):
        qs = WhatsAppTemplate.objects.select_related("owner")

        q = (self.request.GET.get("q") or "").strip()
        template_type = self.request.GET.get("type") or ""
        provider = self.request.GET.get("provider") or ""
        is_active = self.request.GET.get("is_active") or ""

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(slug__icontains=q)
                | Q(provider_template_name__icontains=q)
                | Q(body_text__icontains=q)
            )

        if template_type:
            qs = qs.filter(type=template_type)

        if provider:
            qs = qs.filter(provider=provider)

        if is_active == "1":
            qs = qs.filter(is_active=True)
        elif is_active == "0":
            qs = qs.filter(is_active=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["type_choices"] = WhatsAppTemplate.TemplateType.choices
        context["provider_choices"] = WhatsAppTemplate.Provider.choices
        context["current_q"] = self.request.GET.get("q") or ""
        context["current_type"] = self.request.GET.get("type") or ""
        context["current_provider"] = self.request.GET.get("provider") or ""
        context["current_is_active"] = self.request.GET.get("is_active") or ""

        return context


class WhatsAppTemplateDetailView(MessagingAccessMixin, DetailView):
    model = WhatsAppTemplate
    template_name = "messaging/whatsapptemplate_detail.html"
    context_object_name = "template"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["logs"] = self.object.send_logs.all()[:10]
        return context


class WhatsAppTemplateCreateView(MessagingAccessMixin, CreateView):
    model = WhatsAppTemplate
    form_class = WhatsAppTemplateForm
    template_name = "messaging/whatsapptemplate_form.html"

    @transaction.atomic
    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user

        response = super().form_valid(form)

        if self.object.is_active:
            WhatsAppTemplate.objects.filter(
                type=self.object.type,
                provider=self.object.provider,
                language_code=self.object.language_code,
                is_active=True,
            ).exclude(pk=self.object.pk).update(
                is_active=False,
                is_default_for_type=False,
            )

            self.object.is_active = True
            self.object.is_default_for_type = True
            self.object.save(update_fields=["is_active", "is_default_for_type"])

        messages.success(self.request, "WhatsApp template saved.")
        return response

    def get_success_url(self):
        return reverse("messaging:whatsapp_template_detail", args=[self.object.pk])


class WhatsAppTemplateUpdateView(MessagingAccessMixin, UpdateView):
    model = WhatsAppTemplate
    form_class = WhatsAppTemplateForm
    template_name = "messaging/whatsapptemplate_form.html"

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)

        if self.object.is_active:
            WhatsAppTemplate.objects.filter(
                type=self.object.type,
                provider=self.object.provider,
                language_code=self.object.language_code,
                is_active=True,
            ).exclude(pk=self.object.pk).update(
                is_active=False,
                is_default_for_type=False,
            )

            self.object.is_active = True
            self.object.is_default_for_type = True
            self.object.save(update_fields=["is_active", "is_default_for_type"])

        messages.success(self.request, "WhatsApp template updated.")
        return response

    def get_success_url(self):
        return reverse("messaging:whatsapp_template_detail", args=[self.object.pk])


class WhatsAppTemplateDeleteView(MessagingAccessMixin, DeleteView):
    model = WhatsAppTemplate
    template_name = "messaging/whatsapptemplate_confirm_delete.html"
    success_url = reverse_lazy("messaging:whatsapp_template_list")

    def post(self, request, *args, **kwargs):
        messages.success(request, "WhatsApp template deleted.")
        return super().post(request, *args, **kwargs)


class WhatsAppTemplatePreviewView(MessagingAccessMixin, DetailView):
    model = WhatsAppTemplate
    template_name = "messaging/whatsapptemplate_preview.html"
    context_object_name = "template"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        sample_context = {
            "company_name": "Ocean Clouds",
            "client": {
                "name": "Sample Client",
                "display_name": "Sample Client",
            },
            "vendor": {
                "name": "Sample Vendor",
                "company_name": "Sample Vendor Company",
            },
            "venue": {
                "name": "Sample Wedding Hall",
                "city": "Kochi",
            },
            "event": {
                "name": "Sample Wedding Event",
                "date": "2026-05-07",
                "start_time": "10:00",
                "end_time": "17:00",
            },
            "today": "2026-05-07",
        }

        preview_text = render_template_string(
            self.object.body_text,
            sample_context,
        )

        variable_values = []

        for variable in self.object.variable_order or []:
            variable_values.append(variable)

        context["preview_text"] = preview_text
        context["sample_variables"] = sample_context
        context["variable_values"] = variable_values
        context["back_url"] = reverse(
            "messaging:whatsapp_template_detail",
            args=[self.object.pk],
        )

        return context


class WhatsAppSendLogListView(MessagingAccessMixin, ListView):
    model = WhatsAppSendLog
    template_name = "messaging/whatsapp_log_list.html"
    context_object_name = "logs"
    paginate_by = 30

    def get_queryset(self):
        qs = WhatsAppSendLog.objects.select_related("template")

        status = self.request.GET.get("status") or ""
        template_type = self.request.GET.get("type") or ""
        provider = self.request.GET.get("provider") or ""

        if status:
            qs = qs.filter(status=status)

        if template_type:
            qs = qs.filter(template_type=template_type)

        if provider:
            qs = qs.filter(provider=provider)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = WhatsAppSendLog.Status.choices
        context["type_choices"] = WhatsAppTemplate.TemplateType.choices
        context["provider_choices"] = WhatsAppTemplate.Provider.choices
        context["current_status"] = self.request.GET.get("status") or ""
        context["current_type"] = self.request.GET.get("type") or ""
        context["current_provider"] = self.request.GET.get("provider") or ""
        return context





class TicketListView(LoginRequiredMixin, ListView):
    model = Ticket
    template_name = "messaging/ticket_list.html"
    context_object_name = "tickets"
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user

        # Admin can see all tickets.
        # Other users can see only their own tickets.
        if user_has_role(user, ROLE_ADMIN):
            qs = Ticket.objects.select_related(
                "created_by",
                "assigned_to",
            ).all()
        else:
            qs = Ticket.objects.select_related(
                "created_by",
                "assigned_to",
            ).filter(created_by=user)

        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        priority = self.request.GET.get("priority", "").strip()

        if q:
            qs = qs.filter(
                Q(ticket_number__icontains=q)
                | Q(subject__icontains=q)
                | Q(description__icontains=q)
                | Q(created_by__username__icontains=q)
                | Q(created_by__first_name__icontains=q)
                | Q(created_by__last_name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if priority:
            qs = qs.filter(priority=priority)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        user = self.request.user

        ctx["q"] = self.request.GET.get("q", "").strip()
        ctx["status_filter"] = self.request.GET.get("status", "").strip()
        ctx["priority_filter"] = self.request.GET.get("priority", "").strip()

        ctx["ticket_status_choices"] = TicketStatus.choices
        ctx["ticket_priority_choices"] = TicketPriority.choices

        ctx["is_admin"] = user_has_role(user, ROLE_ADMIN)
        ctx["is_crm_manager"] = user_has_role(user, ROLE_CRM_MANAGER)
        ctx["is_project_manager"] = user_has_role(user, ROLE_PROJECT_MANAGER)
        ctx["is_employee"] = user_has_role(user, ROLE_EMPLOYEE)

        # Temporary old Manager support
        ctx["is_old_manager"] = user_has_role(user, ROLE_MANAGER)

        return ctx


class TicketCreateView(LoginRequiredMixin, CreateView):
    model = Ticket
    form_class = TicketForm
    template_name = "messaging/ticket_form.html"
    success_url = reverse_lazy("messaging:ticket_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        for field_name, field in form.fields.items():
            existing_class = field.widget.attrs.get("class", "")

            if field.widget.__class__.__name__ == "Select":
                field.widget.attrs["class"] = f"{existing_class} form-select".strip()
            elif field.widget.__class__.__name__ == "ClearableFileInput":
                field.widget.attrs["class"] = f"{existing_class} form-control".strip()
            else:
                field.widget.attrs["class"] = f"{existing_class} form-control".strip()

        return form

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class TicketDetailView(LoginRequiredMixin, DetailView):
    model = Ticket
    template_name = "messaging/ticket_detail.html"
    context_object_name = "ticket"

    def get_queryset(self):
        user = self.request.user

        if user_has_role(user, ROLE_ADMIN):
            return Ticket.objects.select_related(
                "created_by",
                "assigned_to",
            ).all()

        return Ticket.objects.select_related(
            "created_by",
            "assigned_to",
        ).filter(created_by=user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        user = self.request.user

        ctx["is_admin"] = user_has_role(user, ROLE_ADMIN)
        ctx["is_crm_manager"] = user_has_role(user, ROLE_CRM_MANAGER)
        ctx["is_project_manager"] = user_has_role(user, ROLE_PROJECT_MANAGER)
        ctx["is_employee"] = user_has_role(user, ROLE_EMPLOYEE)
        ctx["is_old_manager"] = user_has_role(user, ROLE_MANAGER)

        return ctx
