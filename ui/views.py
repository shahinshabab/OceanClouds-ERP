from django.contrib import messages
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import TemplateView, UpdateView

from common.roles import (
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
    user_has_role,
)
from crm.models import Client, Lead, Inquiry
from projects.models import (
    Deliverable,
    DeliverableStatus,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)
from sales.models import Deal

from .forms import ProfileUpdateForm
from .utils import _get_month_info, _monthly_card, _simple_card

User = get_user_model()


@login_required
def home(request):
    user = request.user

    is_admin = user_has_role(user, ROLE_ADMIN)
    is_crm_manager = user_has_role(user, ROLE_CRM_MANAGER)
    is_project_manager = user_has_role(user, ROLE_PROJECT_MANAGER)
    is_employee = user_has_role(user, ROLE_EMPLOYEE)

    if is_admin:
        role_label = "Admin"
    elif is_crm_manager:
        role_label = "CRM Manager"
    elif is_project_manager:
        role_label = "Project Manager"
    elif is_employee:
        role_label = "Employee"
    else:
        role_label = "User"

    this_year, this_month, prev_year, prev_month = _get_month_info()

    summary_cards = []
    monthly_cards = []

    pending_projects_list = None
    pending_tasks_list = None
    pending_deliverables_list = None
    my_pending_tasks_list = None
    my_pending_deliverables_list = None

    show_crm_section = False
    show_project_section = False
    show_employee_section = False

    # ==========================================================
    # ADMIN: full dashboard
    # ==========================================================
    if is_admin:
        show_crm_section = True
        show_project_section = True

        pending_projects_count = Project.objects.exclude(
            status__in=[ProjectStatus.COMPLETED, ProjectStatus.CANCELLED]
        ).count()

        pending_tasks_count = Task.objects.filter(
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
        ).count()

        pending_deliverables_count = Deliverable.objects.filter(
            status__in=[DeliverableStatus.PENDING, DeliverableStatus.IN_PROGRESS]
        ).count()

        open_inquiries_count = Inquiry.objects.filter(
            status__in=["open", "in_progress"]
        ).count()

        summary_cards = [
            _simple_card(
                "Open Projects",
                pending_projects_count,
                "Projects not completed or cancelled",
                "bi-kanban",
                "bg-primary-subtle",
            ),
            _simple_card(
                "Open Tasks",
                pending_tasks_count,
                "Pending and in-progress tasks",
                "bi-list-check",
                "bg-warning-subtle",
            ),
            _simple_card(
                "Open Deliverables",
                pending_deliverables_count,
                "Pending and in-progress deliverables",
                "bi-box-seam",
                "bg-info-subtle",
            ),
            _simple_card(
                "Open Inquiries",
                open_inquiries_count,
                "Open and in-progress inquiries",
                "bi-chat-dots",
                "bg-success-subtle",
            ),
        ]

        leads_qs = Lead.objects.all()
        clients_qs = Client.objects.all()
        deals_qs = Deal.objects.all()

        current_leads = leads_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_leads = leads_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        current_clients = clients_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_clients = clients_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        current_deals = deals_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_deals = deals_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        monthly_cards = [
            _monthly_card("New Leads", current_leads, previous_leads, "bi-person-plus"),
            _monthly_card("New Clients", current_clients, previous_clients, "bi-people"),
            _monthly_card("New Deals", current_deals, previous_deals, "bi-cash-stack"),
        ]

        pending_projects_list = (
            Project.objects.exclude(
                status__in=[ProjectStatus.COMPLETED, ProjectStatus.CANCELLED]
            )
            .select_related("client", "manager")
            .order_by("due_date", "name")[:10]
        )

        pending_tasks_list = (
            Task.objects.filter(
                status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
            )
            .select_related("project", "assigned_to")
            .order_by("due_date", "priority")[:10]
        )

        pending_deliverables_list = (
            Deliverable.objects.filter(
                status__in=[DeliverableStatus.PENDING, DeliverableStatus.IN_PROGRESS]
            )
            .select_related("project", "assigned_to")
            .order_by("due_date", "name")[:10]
        )

    # ==========================================================
    # CRM MANAGER: CRM + Sales only
    # ==========================================================
    elif is_crm_manager:
        show_crm_section = True

        leads_qs = Lead.objects.filter(owner=user)
        clients_qs = Client.objects.filter(owner=user)
        deals_qs = Deal.objects.filter(owner=user)
        inquiries_qs = Inquiry.objects.filter(handled_by=user)

        open_inquiries_count = inquiries_qs.filter(
            status__in=["open", "in_progress"]
        ).count()

        total_leads_count = leads_qs.count()
        total_clients_count = clients_qs.count()
        total_deals_count = deals_qs.count()

        summary_cards = [
            _simple_card(
                "My Leads",
                total_leads_count,
                "Leads owned by you",
                "bi-person-plus",
                "bg-primary-subtle",
            ),
            _simple_card(
                "My Clients",
                total_clients_count,
                "Clients owned by you",
                "bi-people",
                "bg-success-subtle",
            ),
            _simple_card(
                "My Deals",
                total_deals_count,
                "Deals owned by you",
                "bi-cash-stack",
                "bg-warning-subtle",
            ),
            _simple_card(
                "My Open Inquiries",
                open_inquiries_count,
                "Open and in-progress inquiries",
                "bi-chat-dots",
                "bg-info-subtle",
            ),
        ]

        current_leads = leads_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_leads = leads_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        current_clients = clients_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_clients = clients_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        current_deals = deals_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_deals = deals_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        monthly_cards = [
            _monthly_card("New Leads", current_leads, previous_leads, "bi-person-plus"),
            _monthly_card("New Clients", current_clients, previous_clients, "bi-people"),
            _monthly_card("New Deals", current_deals, previous_deals, "bi-cash-stack"),
        ]

    # ==========================================================
    # PROJECT MANAGER: project dashboard only
    # ==========================================================
    elif is_project_manager:
        show_project_section = True

        projects_qs = Project.objects.filter(manager=user)

        pending_projects_count = projects_qs.exclude(
            status__in=[ProjectStatus.COMPLETED, ProjectStatus.CANCELLED]
        ).count()

        pending_tasks_count = Task.objects.filter(
            project__manager=user,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        ).count()

        pending_deliverables_count = Deliverable.objects.filter(
            project__manager=user,
            status__in=[DeliverableStatus.PENDING, DeliverableStatus.IN_PROGRESS],
        ).count()

        open_inquiries_count = Inquiry.objects.filter(
            handled_by=user,
            status__in=["open", "in_progress"],
        ).count()

        summary_cards = [
            _simple_card(
                "My Open Projects",
                pending_projects_count,
                "Projects managed by you",
                "bi-kanban",
                "bg-primary-subtle",
            ),
            _simple_card(
                "Project Tasks",
                pending_tasks_count,
                "Pending and in-progress tasks",
                "bi-list-check",
                "bg-warning-subtle",
            ),
            _simple_card(
                "Project Deliverables",
                pending_deliverables_count,
                "Pending and in-progress deliverables",
                "bi-box-seam",
                "bg-info-subtle",
            ),
            _simple_card(
                "My Open Inquiries",
                open_inquiries_count,
                "Open and in-progress inquiries",
                "bi-chat-dots",
                "bg-success-subtle",
            ),
        ]

        completed_tasks_qs = Task.objects.filter(
            project__manager=user,
            status=TaskStatus.COMPLETED,
        )

        delivered_qs = Deliverable.objects.filter(
            project__manager=user,
            status=DeliverableStatus.DELIVERED,
        )

        current_completed_tasks = completed_tasks_qs.filter(
            updated_at__year=this_year,
            updated_at__month=this_month,
        ).count()
        previous_completed_tasks = completed_tasks_qs.filter(
            updated_at__year=prev_year,
            updated_at__month=prev_month,
        ).count()

        current_delivered = delivered_qs.filter(
            updated_at__year=this_year,
            updated_at__month=this_month,
        ).count()
        previous_delivered = delivered_qs.filter(
            updated_at__year=prev_year,
            updated_at__month=prev_month,
        ).count()

        current_projects = projects_qs.filter(
            created_at__year=this_year,
            created_at__month=this_month,
        ).count()
        previous_projects = projects_qs.filter(
            created_at__year=prev_year,
            created_at__month=prev_month,
        ).count()

        monthly_cards = [
            _monthly_card(
                "New Projects",
                current_projects,
                previous_projects,
                "bi-folder-plus",
            ),
            _monthly_card(
                "Completed Tasks",
                current_completed_tasks,
                previous_completed_tasks,
                "bi-check2-circle",
            ),
            _monthly_card(
                "Delivered Items",
                current_delivered,
                previous_delivered,
                "bi-send-check",
            ),
        ]

        pending_projects_list = (
            Project.objects.filter(manager=user)
            .exclude(status__in=[ProjectStatus.COMPLETED, ProjectStatus.CANCELLED])
            .select_related("client", "manager")
            .order_by("due_date", "name")[:10]
        )

        pending_tasks_list = (
            Task.objects.filter(
                project__manager=user,
                status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
            )
            .select_related("project", "assigned_to")
            .order_by("due_date", "priority")[:10]
        )

        pending_deliverables_list = (
            Deliverable.objects.filter(
                project__manager=user,
                status__in=[DeliverableStatus.PENDING, DeliverableStatus.IN_PROGRESS],
            )
            .select_related("project", "assigned_to")
            .order_by("due_date", "name")[:10]
        )

    # ==========================================================
    # EMPLOYEE: own work only
    # ==========================================================
    elif is_employee:
        show_employee_section = True

        my_pending_tasks_count = Task.objects.filter(
            assigned_to=user,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        ).count()

        my_pending_deliverables_count = Deliverable.objects.filter(
            assigned_to=user,
            status__in=[DeliverableStatus.PENDING, DeliverableStatus.IN_PROGRESS],
        ).count()

        my_open_inquiries_count = Inquiry.objects.filter(
            handled_by=user,
            status__in=["open", "in_progress"],
        ).count()

        summary_cards = [
            _simple_card(
                "My Tasks",
                my_pending_tasks_count,
                "Pending and in-progress tasks",
                "bi-list-check",
                "bg-warning-subtle",
            ),
            _simple_card(
                "My Deliverables",
                my_pending_deliverables_count,
                "Pending and in-progress deliverables",
                "bi-box-seam",
                "bg-info-subtle",
            ),
            _simple_card(
                "My Inquiries",
                my_open_inquiries_count,
                "Open and in-progress inquiries",
                "bi-chat-dots",
                "bg-success-subtle",
            ),
        ]

        completed_tasks_qs = Task.objects.filter(
            assigned_to=user,
            status=TaskStatus.COMPLETED,
        )

        delivered_qs = Deliverable.objects.filter(
            assigned_to=user,
            status=DeliverableStatus.DELIVERED,
        )

        inquiries_qs = Inquiry.objects.filter(handled_by=user)

        current_completed_tasks = completed_tasks_qs.filter(
            updated_at__year=this_year,
            updated_at__month=this_month,
        ).count()
        previous_completed_tasks = completed_tasks_qs.filter(
            updated_at__year=prev_year,
            updated_at__month=prev_month,
        ).count()

        current_delivered = delivered_qs.filter(
            updated_at__year=this_year,
            updated_at__month=this_month,
        ).count()
        previous_delivered = delivered_qs.filter(
            updated_at__year=prev_year,
            updated_at__month=prev_month,
        ).count()

        current_inquiries = inquiries_qs.filter(
            updated_at__year=this_year,
            updated_at__month=this_month,
        ).count()
        previous_inquiries = inquiries_qs.filter(
            updated_at__year=prev_year,
            updated_at__month=prev_month,
        ).count()

        monthly_cards = [
            _monthly_card(
                "Completed Tasks",
                current_completed_tasks,
                previous_completed_tasks,
                "bi-check2-circle",
            ),
            _monthly_card(
                "Delivered Items",
                current_delivered,
                previous_delivered,
                "bi-send-check",
            ),
            _monthly_card(
                "Handled Inquiries",
                current_inquiries,
                previous_inquiries,
                "bi-chat-square-text",
            ),
        ]

        my_pending_tasks_list = (
            Task.objects.filter(
                assigned_to=user,
                status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
            )
            .select_related("project")
            .order_by("due_date", "priority")[:10]
        )

        my_pending_deliverables_list = (
            Deliverable.objects.filter(
                assigned_to=user,
                status__in=[DeliverableStatus.PENDING, DeliverableStatus.IN_PROGRESS],
            )
            .select_related("project")
            .order_by("due_date", "name")[:10]
        )

    context = {
        "role_label": role_label,
        "is_admin": is_admin,
        "is_crm_manager": is_crm_manager,
        "is_project_manager": is_project_manager,
        "is_employee": is_employee,
        "show_crm_section": show_crm_section,
        "show_project_section": show_project_section,
        "show_employee_section": show_employee_section,
        "summary_cards": summary_cards,
        "monthly_cards": monthly_cards,
        "pending_projects_list": pending_projects_list,
        "pending_tasks_list": pending_tasks_list,
        "pending_deliverables_list": pending_deliverables_list,
        "my_pending_tasks_list": my_pending_tasks_list,
        "my_pending_deliverables_list": my_pending_deliverables_list,
    }

    return render(request, "ui/home.html", context)


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            request.session.set_expiry(settings.LOGIN_SESSION_MAX_SECONDS)
            messages.success(request, "Welcome back!", extra_tags="scope:auth")
            return redirect("ui:home")

        messages.error(
            request,
            "Invalid username or password",
            extra_tags="scope:auth",
        )

    return render(request, "ui/login.html")


def logout_view(request):
    logout(request)
    messages.info(
        request,
        "You have been logged out.",
        extra_tags="scope:auth",
    )
    return redirect("ui:login")


class ProfileDetailView(LoginRequiredMixin, TemplateView):
    template_name = "ui/profile_detail.html"


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = ProfileUpdateForm
    template_name = "ui/profile_edit.html"
    success_url = reverse_lazy("ui:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        for field_name, field in form.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

        return form

    def form_valid(self, form):
        messages.success(self.request, "Profile updated successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please fix the errors below.")
        return super().form_invalid(form)


class ProfilePasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "ui/profile_password.html"
    success_url = reverse_lazy("ui:profile")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        for field_name, field in form.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

        return form

    def form_valid(self, form):
        messages.success(self.request, "Password changed successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please fix the errors below.")
        return super().form_invalid(form)
