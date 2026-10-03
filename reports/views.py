# reports/views.py

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import TemplateView

from common.mixins import (
    ReportAccessMixin,
    SalesReportAccessMixin,
    ProjectReportAccessMixin,
    EmployeeReportAccessMixin,
)
from common.models import UserLoginSession
from common.roles import (
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
    user_has_role,
)

from crm.models import Inquiry, Lead, Client, Contact, Review

from sales.models import (
    Deal,
    Proposal,
    Contract,
    Invoice,
    Payment,
    DealStage,
    ProposalStatus,
    ContractStatus,
    InvoiceStatus,
)

from projects.models import (
    Project,
    Task,
    Deliverable,
    WorkSession,
    ProjectStatus,
    TaskStatus,
    DeliverableStatus,
    WorkSessionStatus,
)
from .utils import (
    _base_date_filter,
    _build_login_month_table,
    _build_login_week_chart,
    _employee_options_for_user,
    _get_date_range,
    _int,
    _money,
    _selected_user_id,
    _user_display,
    _users_in_role,
)

try:
    from weasyprint import HTML
except ImportError:
    HTML = None


User = get_user_model()


# ============================================================
# Helpers
# ============================================================

# ============================================================
# PDF Mixin
# ============================================================

class ReportPDFMixin:
    """
    Adds PDF download support.

    Example:
    /reports/employee/?download=pdf
    """

    pdf_template_name = None
    pdf_filename = "report.pdf"

    def get_pdf_filename(self):
        return self.pdf_filename

    def get_pdf_url(self):
        params = self.request.GET.copy()
        params["download"] = "pdf"
        return f"{self.request.path}?{params.urlencode()}"

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get("download") == "pdf":
            if HTML is None:
                raise Http404("PDF generation is not available. Install WeasyPrint.")

            template_name = self.pdf_template_name or self.template_name

            html_string = render_to_string(
                template_name,
                context,
                request=self.request,
            )

            pdf_file = HTML(
                string=html_string,
                base_url=self.request.build_absolute_uri("/"),
            ).write_pdf()

            response = HttpResponse(pdf_file, content_type="application/pdf")
            response["Content-Disposition"] = (
                f'attachment; filename="{self.get_pdf_filename()}"'
            )
            return response

        return super().render_to_response(context, **response_kwargs)


# ============================================================
# Dashboard
# ============================================================

class ReportDashboardView(ReportAccessMixin, TemplateView):
    template_name = "reports/report_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user = self.request.user

        context["can_view_sales_report"] = user_has_role(
            user,
            ROLE_ADMIN,
            ROLE_CRM_MANAGER,
        )

        context["can_view_project_report"] = user_has_role(
            user,
            ROLE_ADMIN,
            ROLE_PROJECT_MANAGER,
        )

        context["can_view_employee_report"] = user_has_role(
            user,
            ROLE_ADMIN,
            ROLE_PROJECT_MANAGER,
            ROLE_EMPLOYEE,
        )

        return context


# ============================================================
# Sales Report
# ============================================================

class SalesReportView(SalesReportAccessMixin, ReportPDFMixin, TemplateView):
    template_name = "reports/sales_report.html"
    pdf_template_name = "reports/sales_pdf.html"
    pdf_filename = "sales_report.pdf"

    def get_selected_crm_user(self):
        request = self.request
        current_user = request.user

        selected_id = _selected_user_id(request)

        if user_has_role(current_user, ROLE_ADMIN):
            if selected_id:
                return User.objects.filter(
                    id=selected_id,
                    groups__name=ROLE_CRM_MANAGER,
                    is_active=True,
                ).first()

            return None

        return current_user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        date_from, date_to = _get_date_range(self.request)
        selected_user = self.get_selected_crm_user()

        inquiries = Inquiry.objects.select_related(
            "owner",
            "client",
            "lead",
        )

        leads = Lead.objects.select_related(
            "owner",
            "client",
            "inquiry",
        )

        clients = Client.objects.select_related("owner")
        contacts = Contact.objects.select_related("owner", "client")
        reviews = Review.objects.select_related("owner", "client")

        if selected_user:
            inquiries = inquiries.filter(owner=selected_user)
            leads = leads.filter(owner=selected_user)
            clients = clients.filter(owner=selected_user)
            contacts = contacts.filter(owner=selected_user)
            reviews = reviews.filter(owner=selected_user)

        inquiries_in_period = _base_date_filter(inquiries, "created_at", date_from, date_to)
        leads_in_period = _base_date_filter(leads, "created_at", date_from, date_to)
        clients_in_period = _base_date_filter(clients, "created_at", date_from, date_to)
        contacts_in_period = _base_date_filter(contacts, "created_at", date_from, date_to)
        reviews_in_period = _base_date_filter(reviews, "created_at", date_from, date_to)

        deals = Deal.objects.select_related(
            "owner",
            "client",
            "lead",
        )

        proposals = Proposal.objects.select_related(
            "owner",
            "deal",
            "deal__client",
            "deal__lead",
        )

        contracts = Contract.objects.select_related(
            "owner",
            "deal",
            "proposal",
            "deal__client",
            "deal__lead",
        )

        invoices = Invoice.objects.select_related(
            "owner",
            "deal",
            "contract",
            "deal__client",
            "deal__lead",
        )

        payments = Payment.objects.select_related(
            "owner",
            "invoice",
            "invoice__deal",
            "invoice__deal__client",
            "invoice__deal__lead",
            "received_by",
        )

        if selected_user:
            deals = deals.filter(owner=selected_user)
            proposals = proposals.filter(owner=selected_user)
            contracts = contracts.filter(owner=selected_user)
            invoices = invoices.filter(owner=selected_user)
            payments = payments.filter(owner=selected_user)

        deals_in_period = _base_date_filter(deals, "created_at", date_from, date_to)
        proposals_in_period = _base_date_filter(proposals, "created_at", date_from, date_to)
        contracts_in_period = _base_date_filter(contracts, "created_at", date_from, date_to)
        invoices_in_period = _base_date_filter(invoices, "created_at", date_from, date_to)
        payments_in_period = _base_date_filter(payments, "created_at", date_from, date_to)

        inquiry_to_lead_count = inquiries_in_period.filter(
            Q(lead__isnull=False) |
            Q(status=Inquiry.STATUS_CONVERTED_TO_LEAD)
        ).distinct().count()

        lead_to_deal_count = leads_in_period.filter(
            deals__isnull=False
        ).distinct().count()

        deal_to_contract_count = deals_in_period.filter(
            contracts__isnull=False
        ).distinct().count()

        deal_to_invoice_count = deals_in_period.filter(
            invoices__isnull=False
        ).distinct().count()

        invoice_total = _money(
            invoices_in_period.aggregate(total=Sum("total"))["total"]
        )

        amount_paid_total = _money(
            invoices_in_period.aggregate(total=Sum("amount_paid"))["total"]
        )

        payment_received_total = _money(
            payments_in_period.aggregate(total=Sum("amount"))["total"]
        )

        outstanding_total = invoice_total - amount_paid_total

        inquiry_status_counts = inquiries_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        inquiry_channel_counts = inquiries_in_period.values("channel").annotate(
            count=Count("id")
        ).order_by("channel")

        lead_status_counts = leads_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        deal_stage_counts = deals_in_period.values("stage").annotate(
            count=Count("id")
        ).order_by("stage")

        proposal_status_counts = proposals_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        contract_status_counts = contracts_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        invoice_status_counts = invoices_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        inquiry_count = inquiries_in_period.count()
        lead_count = leads_in_period.count()
        deal_count = deals_in_period.count()

        inquiry_to_lead_rate = round((inquiry_to_lead_count / inquiry_count) * 100, 2) if inquiry_count else 0
        lead_to_deal_rate = round((lead_to_deal_count / lead_count) * 100, 2) if lead_count else 0
        deal_to_contract_rate = round((deal_to_contract_count / deal_count) * 100, 2) if deal_count else 0

        context.update({
            "report_title": "Sales Report",
            "date_from": date_from,
            "date_to": date_to,
            "selected_user": selected_user,
            "selected_user_name": _user_display(selected_user),
            "crm_managers": _users_in_role(ROLE_CRM_MANAGER),
            "pdf_download_url": self.get_pdf_url(),

            "summary": {
                "inquiry_count": inquiry_count,
                "lead_count": lead_count,
                "client_count": clients_in_period.count(),
                "contact_count": contacts_in_period.count(),
                "review_count": reviews_in_period.count(),

                "deal_count": deal_count,
                "proposal_count": proposals_in_period.count(),
                "contract_count": contracts_in_period.count(),
                "invoice_count": invoices_in_period.count(),
                "payment_count": payments_in_period.count(),

                "inquiry_to_lead_count": inquiry_to_lead_count,
                "lead_to_deal_count": lead_to_deal_count,
                "deal_to_contract_count": deal_to_contract_count,
                "deal_to_invoice_count": deal_to_invoice_count,

                "inquiry_to_lead_rate": inquiry_to_lead_rate,
                "lead_to_deal_rate": lead_to_deal_rate,
                "deal_to_contract_rate": deal_to_contract_rate,

                "invoice_total": invoice_total,
                "amount_paid_total": amount_paid_total,
                "payment_received_total": payment_received_total,
                "outstanding_total": outstanding_total,

                "won_deals": deals_in_period.filter(stage=DealStage.WON).count(),
                "lost_deals": deals_in_period.filter(stage=DealStage.LOST).count(),
                "accepted_proposals": proposals_in_period.filter(status=ProposalStatus.ACCEPTED).count(),
                "signed_contracts": contracts_in_period.filter(status=ContractStatus.SIGNED).count(),
                "paid_invoices": invoices_in_period.filter(status=InvoiceStatus.PAID).count(),
                "overdue_invoices": invoices_in_period.filter(status=InvoiceStatus.OVERDUE).count(),
            },

            "inquiry_status_counts": inquiry_status_counts,
            "inquiry_channel_counts": inquiry_channel_counts,
            "lead_status_counts": lead_status_counts,
            "deal_stage_counts": deal_stage_counts,
            "proposal_status_counts": proposal_status_counts,
            "contract_status_counts": contract_status_counts,
            "invoice_status_counts": invoice_status_counts,

            "recent_inquiries": inquiries_in_period.order_by("-created_at")[:10],
            "recent_leads": leads_in_period.order_by("-created_at")[:10],
            "recent_deals": deals_in_period.order_by("-created_at")[:10],
            "recent_invoices": invoices_in_period.order_by("-created_at")[:10],
            "recent_payments": payments_in_period.order_by("-created_at")[:10],
        })

        return context


# ============================================================
# Project Report
# ============================================================

class ProjectReportView(ProjectReportAccessMixin, ReportPDFMixin, TemplateView):
    template_name = "reports/project_report.html"
    pdf_template_name = "reports/project_pdf.html"
    pdf_filename = "project_report.pdf"

    def get_selected_project_manager(self):
        request = self.request
        current_user = request.user

        selected_id = _selected_user_id(request)

        if user_has_role(current_user, ROLE_ADMIN):
            if selected_id:
                return User.objects.filter(
                    id=selected_id,
                    groups__name=ROLE_PROJECT_MANAGER,
                    is_active=True,
                ).first()

            return None

        return current_user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        date_from, date_to = _get_date_range(self.request)
        selected_user = self.get_selected_project_manager()
        today = timezone.localdate()

        projects = Project.objects.select_related(
            "owner",
            "client",
            "deal",
            "event",
            "manager",
        ).prefetch_related(
            "tasks",
            "deliverables",
        )

        if selected_user:
            projects = projects.filter(manager=selected_user)

        projects_in_period = _base_date_filter(projects, "created_at", date_from, date_to)

        tasks = Task.objects.select_related(
            "owner",
            "project",
            "project__manager",
            "assigned_to",
        )

        deliverables = Deliverable.objects.select_related(
            "owner",
            "project",
            "project__manager",
            "assigned_to",
        )

        work_sessions = WorkSession.objects.select_related(
            "owner",
            "user",
            "project",
            "project__manager",
            "task",
            "deliverable",
        )

        if selected_user:
            tasks = tasks.filter(project__manager=selected_user)
            deliverables = deliverables.filter(project__manager=selected_user)
            work_sessions = work_sessions.filter(project__manager=selected_user)

        tasks_in_period = _base_date_filter(tasks, "created_at", date_from, date_to)
        deliverables_in_period = _base_date_filter(deliverables, "created_at", date_from, date_to)
        work_sessions_in_period = _base_date_filter(work_sessions, "started_at", date_from, date_to)

        total_work_seconds = _int(
            work_sessions_in_period.aggregate(total=Sum("work_seconds"))["total"]
        )

        total_work_hours = round(total_work_seconds / 3600, 2)

        overdue_projects = projects.filter(
            due_date__lt=today,
        ).exclude(
            status__in=[
                ProjectStatus.COMPLETED,
                ProjectStatus.CANCELLED,
            ]
        )

        overdue_tasks = tasks.filter(
            due_date__lt=today,
        ).exclude(
            status__in=[
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
            ]
        )

        overdue_deliverables = deliverables.filter(
            due_date__lt=today,
        ).exclude(
            status__in=[
                DeliverableStatus.DELIVERED,
                DeliverableStatus.CANCELLED,
            ]
        )

        project_status_counts = projects_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        task_status_counts = tasks_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        deliverable_status_counts = deliverables_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        task_department_counts = tasks_in_period.values("department").annotate(
            count=Count("id")
        ).order_by("department")

        deliverable_department_counts = deliverables_in_period.values("department").annotate(
            count=Count("id")
        ).order_by("department")

        project_count = projects_in_period.count()
        completed_project_count = projects_in_period.filter(status=ProjectStatus.COMPLETED).count()

        completion_rate = round((completed_project_count / project_count) * 100, 2) if project_count else 0

        context.update({
            "report_title": "Project Report",
            "date_from": date_from,
            "date_to": date_to,
            "selected_user": selected_user,
            "selected_user_name": _user_display(selected_user),
            "project_managers": _users_in_role(ROLE_PROJECT_MANAGER),
            "pdf_download_url": self.get_pdf_url(),

            "summary": {
                "project_count": project_count,
                "active_project_count": projects_in_period.filter(status=ProjectStatus.ACTIVE).count(),
                "completed_project_count": completed_project_count,
                "on_hold_project_count": projects_in_period.filter(status=ProjectStatus.ON_HOLD).count(),
                "cancelled_project_count": projects_in_period.filter(status=ProjectStatus.CANCELLED).count(),
                "overdue_project_count": overdue_projects.count(),

                "task_count": tasks_in_period.count(),
                "completed_task_count": tasks_in_period.filter(status=TaskStatus.COMPLETED).count(),
                "in_progress_task_count": tasks_in_period.filter(status=TaskStatus.IN_PROGRESS).count(),
                "paused_task_count": tasks_in_period.filter(status=TaskStatus.PAUSED).count(),
                "overdue_task_count": overdue_tasks.count(),

                "deliverable_count": deliverables_in_period.count(),
                "delivered_count": deliverables_in_period.filter(status=DeliverableStatus.DELIVERED).count(),
                "ready_to_deliver_count": deliverables_in_period.filter(status=DeliverableStatus.READY_TO_DELIVER).count(),
                "in_progress_deliverable_count": deliverables_in_period.filter(status=DeliverableStatus.IN_PROGRESS).count(),
                "overdue_deliverable_count": overdue_deliverables.count(),

                "work_session_count": work_sessions_in_period.count(),
                "active_work_session_count": work_sessions.filter(status=WorkSessionStatus.ACTIVE).count(),
                "paused_work_session_count": work_sessions.filter(status=WorkSessionStatus.PAUSED).count(),
                "total_work_seconds": total_work_seconds,
                "total_work_hours": total_work_hours,

                "completion_rate": completion_rate,
            },

            "project_status_counts": project_status_counts,
            "task_status_counts": task_status_counts,
            "deliverable_status_counts": deliverable_status_counts,
            "task_department_counts": task_department_counts,
            "deliverable_department_counts": deliverable_department_counts,

            "recent_projects": projects_in_period.order_by("-created_at")[:10],
            "overdue_projects": overdue_projects.order_by("due_date")[:10],
            "recent_tasks": tasks_in_period.order_by("-created_at")[:10],
            "overdue_tasks": overdue_tasks.order_by("due_date")[:10],
            "recent_deliverables": deliverables_in_period.order_by("-created_at")[:10],
            "overdue_deliverables": overdue_deliverables.order_by("due_date")[:10],
        })

        return context


# ============================================================
# Employee Report
# ============================================================

class EmployeeWorkReportView(EmployeeReportAccessMixin, ReportPDFMixin, TemplateView):
    template_name = "reports/employee_report.html"
    pdf_template_name = "reports/employee_pdf.html"
    pdf_filename = "employee_report.pdf"

    def get_selected_employee(self):
        request = self.request
        current_user = request.user

        selected_id = _selected_user_id(request)

        if user_has_role(current_user, ROLE_ADMIN, ROLE_PROJECT_MANAGER):
            if selected_id:
                return User.objects.filter(
                    id=selected_id,
                    is_active=True,
                    groups__name__in=[
                        ROLE_EMPLOYEE,
                        ROLE_PROJECT_MANAGER,
                    ],
                ).distinct().first()

            return None

        return current_user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        date_from, date_to = _get_date_range(self.request)
        selected_user = self.get_selected_employee()
        today = timezone.localdate()
        current_user = self.request.user

        tasks = Task.objects.select_related(
            "owner",
            "project",
            "assigned_to",
            "project__manager",
        )

        deliverables = Deliverable.objects.select_related(
            "owner",
            "project",
            "assigned_to",
            "project__manager",
        )

        work_sessions = WorkSession.objects.select_related(
            "owner",
            "user",
            "project",
            "task",
            "deliverable",
        )

        login_sessions = UserLoginSession.objects.select_related("user")

        # Project Manager can see employees only under managed projects.
        if user_has_role(current_user, ROLE_PROJECT_MANAGER) and not user_has_role(current_user, ROLE_ADMIN):
            tasks = tasks.filter(project__manager=current_user)
            deliverables = deliverables.filter(project__manager=current_user)
            work_sessions = work_sessions.filter(project__manager=current_user)

            visible_employee_ids = (
                WorkSession.objects
                .filter(project__manager=current_user)
                .values_list("user_id", flat=True)
                .distinct()
            )

            login_sessions = login_sessions.filter(
                Q(user_id__in=visible_employee_ids) | Q(user=current_user)
            )

        # Normal employee can see only own login sessions.
        if user_has_role(current_user, ROLE_EMPLOYEE) and not user_has_role(
            current_user,
            ROLE_ADMIN,
            ROLE_PROJECT_MANAGER,
        ):
            login_sessions = login_sessions.filter(user=current_user)

        if selected_user:
            tasks = tasks.filter(assigned_to=selected_user)
            deliverables = deliverables.filter(assigned_to=selected_user)
            work_sessions = work_sessions.filter(user=selected_user)
            login_sessions = login_sessions.filter(user=selected_user)

        tasks_in_period = _base_date_filter(tasks, "created_at", date_from, date_to)
        deliverables_in_period = _base_date_filter(deliverables, "created_at", date_from, date_to)
        work_sessions_in_period = _base_date_filter(work_sessions, "started_at", date_from, date_to)

        task_work_sessions = work_sessions_in_period.filter(task__isnull=False)
        deliverable_work_sessions = work_sessions_in_period.filter(deliverable__isnull=False)

        total_work_seconds = _int(
            work_sessions_in_period.aggregate(total=Sum("work_seconds"))["total"]
        )

        task_work_seconds = _int(
            task_work_sessions.aggregate(total=Sum("work_seconds"))["total"]
        )

        deliverable_work_seconds = _int(
            deliverable_work_sessions.aggregate(total=Sum("work_seconds"))["total"]
        )

        attendance_days = (
            work_sessions_in_period
            .datetimes("started_at", "day")
            .count()
        )

        active_sessions = work_sessions.filter(status=WorkSessionStatus.ACTIVE)
        paused_sessions = work_sessions.filter(status=WorkSessionStatus.PAUSED)

        overdue_tasks = tasks.filter(
            due_date__lt=today,
        ).exclude(
            status__in=[
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
            ]
        )

        overdue_deliverables = deliverables.filter(
            due_date__lt=today,
        ).exclude(
            status__in=[
                DeliverableStatus.DELIVERED,
                DeliverableStatus.CANCELLED,
            ]
        )

        task_status_counts = tasks_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        deliverable_status_counts = deliverables_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        work_status_counts = work_sessions_in_period.values("status").annotate(
            count=Count("id")
        ).order_by("status")

        work_by_employee = (
            work_sessions_in_period
            .values(
                "user_id",
                "user__username",
                "user__first_name",
                "user__last_name",
            )
            .annotate(
                session_count=Count("id"),
                total_seconds=Sum("work_seconds"),
            )
            .order_by("-total_seconds")
        )

        for row in work_by_employee:
            seconds = row["total_seconds"] or 0
            row["total_hours"] = round(seconds / 3600, 2)

        login_chart = _build_login_week_chart(
            self.request,
            login_sessions,
        )

        login_table = _build_login_month_table(
            login_sessions_qs=login_sessions,
            work_sessions_qs=work_sessions,
            date_from=date_from,
            date_to=date_to,
        )

        context.update({
            "report_title": "Employee Work Report",
            "date_from": date_from,
            "date_to": date_to,
            "selected_user": selected_user,
            "selected_user_name": _user_display(selected_user),
            "employees": _employee_options_for_user(current_user),
            "pdf_download_url": self.get_pdf_url(),

            "login_chart": login_chart,
            "login_table": login_table,

            "summary": {
                "assigned_task_count": tasks_in_period.count(),
                "completed_task_count": tasks_in_period.filter(status=TaskStatus.COMPLETED).count(),
                "in_progress_task_count": tasks_in_period.filter(status=TaskStatus.IN_PROGRESS).count(),
                "paused_task_count": tasks_in_period.filter(status=TaskStatus.PAUSED).count(),
                "overdue_task_count": overdue_tasks.count(),

                "assigned_deliverable_count": deliverables_in_period.count(),
                "delivered_count": deliverables_in_period.filter(status=DeliverableStatus.DELIVERED).count(),
                "ready_to_deliver_count": deliverables_in_period.filter(status=DeliverableStatus.READY_TO_DELIVER).count(),
                "in_progress_deliverable_count": deliverables_in_period.filter(status=DeliverableStatus.IN_PROGRESS).count(),
                "overdue_deliverable_count": overdue_deliverables.count(),

                "work_session_count": work_sessions_in_period.count(),
                "active_session_count": active_sessions.count(),
                "paused_session_count": paused_sessions.count(),
                "attendance_days": attendance_days,

                "total_work_seconds": total_work_seconds,
                "total_work_hours": round(total_work_seconds / 3600, 2),

                "task_work_seconds": task_work_seconds,
                "task_work_hours": round(task_work_seconds / 3600, 2),

                "deliverable_work_seconds": deliverable_work_seconds,
                "deliverable_work_hours": round(deliverable_work_seconds / 3600, 2),

                "login_total_hours": login_table["total_login_hours"],
                "login_total_hm": login_table["total_login_hm"],
                "login_work_hours": login_table["total_work_hours"],
                "login_work_hm": login_table["total_work_hm"],
            },

            "task_status_counts": task_status_counts,
            "deliverable_status_counts": deliverable_status_counts,
            "work_status_counts": work_status_counts,
            "work_by_employee": work_by_employee,

            "active_sessions": active_sessions.order_by("-started_at")[:10],
            "paused_sessions": paused_sessions.order_by("-started_at")[:10],
            "recent_work_sessions": work_sessions_in_period.order_by("-started_at")[:20],
            "recent_tasks": tasks_in_period.order_by("-created_at")[:10],
            "overdue_tasks": overdue_tasks.order_by("due_date")[:10],
            "recent_deliverables": deliverables_in_period.order_by("-created_at")[:10],
            "overdue_deliverables": overdue_deliverables.order_by("due_date")[:10],
        })

        return context
