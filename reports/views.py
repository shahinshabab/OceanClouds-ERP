# reports/views.py

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import TemplateView

from common.mixins import (
    ReportAccessMixin,
    SalesReportAccessMixin,
    ProjectReportAccessMixin,
    EmployeeReportAccessMixin,
    AttendanceAccessMixin,
)
from common.models import (
    CheckoutReviewStatus,
    LeaveRequest,
    LeaveStatus,
    UserLoginSession,
)
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
    _build_attendance_summary,
    _build_login_month_table,
    _build_login_week_chart,
    _employee_options_for_user,
    _format_seconds_hm,
    _get_date_range,
    _int,
    _money,
    _selected_user_id,
    _sum_work_session_seconds,
    _user_display,
    _users_in_role,
)
from .forms import CheckoutCorrectionForm, LeaveRequestForm

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
        )

        context["can_view_attendance"] = user_has_role(
            user,
            ROLE_ADMIN,
            ROLE_PROJECT_MANAGER,
        )

        return context


class AttendanceDashboardView(AttendanceAccessMixin, TemplateView):
    template_name = "reports/attendance.html"

    def visible_employees(self):
        return _employee_options_for_user(self.request.user)

    def visible_employee_ids(self):
        return set(self.visible_employees().values_list("id", flat=True))

    def can_review_user(self, employee_id):
        return (
            employee_id != self.request.user.id
            and employee_id in self.visible_employee_ids()
            and self.request.user.has_perm("common.review_attendance")
        )

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")

        if action == "submit_checkout":
            login_session = get_object_or_404(
                UserLoginSession,
                pk=request.POST.get("session_id"),
                user=request.user,
                checkout_review_status__in=[
                    CheckoutReviewStatus.PENDING,
                    CheckoutReviewStatus.REJECTED,
                ],
            )
            form = CheckoutCorrectionForm(request.POST, login_session=login_session)
            if form.is_valid():
                login_session.requested_logout_at = form.cleaned_data["requested_logout_at"]
                login_session.checkout_request_note = form.cleaned_data["checkout_request_note"]
                login_session.reviewed_by = None
                login_session.reviewed_at = None
                login_session.review_note = ""
                login_session.checkout_review_status = CheckoutReviewStatus.PENDING
                login_session.save(
                    update_fields=[
                        "requested_logout_at",
                        "checkout_request_note",
                        "reviewed_by",
                        "reviewed_at",
                        "review_note",
                        "checkout_review_status",
                    ]
                )
                messages.success(request, "Missing checkout submitted for approval.")
            else:
                messages.error(request, "Please provide a valid checkout time and reason.")

        elif action in ["approve_checkout", "reject_checkout"]:
            login_session = get_object_or_404(
                UserLoginSession,
                pk=request.POST.get("session_id"),
                checkout_review_status=CheckoutReviewStatus.PENDING,
                requested_logout_at__isnull=False,
            )
            if not self.can_review_user(login_session.user_id):
                return HttpResponseForbidden("You cannot review this employee's attendance.")
            review_note = request.POST.get("review_note", "").strip()
            if action == "reject_checkout" and not review_note:
                messages.error(request, "A rejection reason is required.")
                return redirect("reports:attendance")
            login_session.checkout_review_status = (
                CheckoutReviewStatus.APPROVED
                if action == "approve_checkout"
                else CheckoutReviewStatus.REJECTED
            )
            login_session.reviewed_by = request.user
            login_session.reviewed_at = timezone.now()
            login_session.review_note = review_note
            login_session.save(
                update_fields=[
                    "checkout_review_status",
                    "reviewed_by",
                    "reviewed_at",
                    "review_note",
                ]
            )
            messages.success(request, "Attendance correction reviewed.")

        elif action == "submit_leave":
            form = LeaveRequestForm(request.POST)
            if form.is_valid():
                leave_request = form.save(commit=False)
                leave_request.user = request.user
                leave_request.save()
                messages.success(request, "Leave request submitted.")
            else:
                messages.error(request, "Please correct the leave request details.")

        elif action in ["approve_leave", "reject_leave"]:
            leave_request = get_object_or_404(
                LeaveRequest,
                pk=request.POST.get("leave_id"),
                status=LeaveStatus.PENDING,
            )
            if not (
                self.can_review_user(leave_request.user_id)
                and request.user.has_perm("common.review_leave_requests")
            ):
                return HttpResponseForbidden("You cannot review this employee's leave.")
            review_note = request.POST.get("review_note", "").strip()
            if action == "reject_leave" and not review_note:
                messages.error(request, "A rejection reason is required.")
                return redirect("reports:attendance")
            leave_request.status = (
                LeaveStatus.APPROVED if action == "approve_leave" else LeaveStatus.REJECTED
            )
            leave_request.reviewed_by = request.user
            leave_request.reviewed_at = timezone.now()
            leave_request.review_note = review_note
            leave_request.save(
                update_fields=["status", "reviewed_by", "reviewed_at", "review_note"]
            )
            messages.success(request, "Leave request reviewed.")

        elif action == "cancel_leave":
            leave_request = get_object_or_404(
                LeaveRequest,
                pk=request.POST.get("leave_id"),
                user=request.user,
                status=LeaveStatus.PENDING,
            )
            leave_request.status = LeaveStatus.CANCELLED
            leave_request.save(update_fields=["status"])
            messages.success(request, "Leave request cancelled.")

        return redirect("reports:attendance")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date_from, date_to = _get_date_range(self.request)
        employees = self.visible_employees()
        visible_ids = set(employees.values_list("id", flat=True))
        selected_id = _selected_user_id(self.request)
        if selected_id not in visible_ids:
            selected_id = None

        sessions = UserLoginSession.objects.filter(
            user_id__in=visible_ids,
        ).filter(
            Q(login_at__date__gte=date_from, login_at__date__lte=date_to)
            | Q(checkout_review_status=CheckoutReviewStatus.PENDING)
            | Q(logout_at__isnull=True)
        ).select_related("user", "reviewed_by")
        leaves = LeaveRequest.objects.filter(
            user_id__in=visible_ids,
        ).filter(
            Q(start_date__lte=date_to, end_date__gte=date_from)
            | Q(status=LeaveStatus.PENDING)
        ).select_related("user", "reviewed_by")
        if selected_id:
            sessions = sessions.filter(user_id=selected_id)
            leaves = leaves.filter(user_id=selected_id)

        session_rows = []
        for session in sessions.order_by("-login_at"):
            display_end = session.approved_logout_at
            if session.logout_at is None:
                display_end = min(timezone.now(), session.expires_at or timezone.now())
            seconds = max(
                int((display_end - session.login_at).total_seconds()),
                0,
            ) if display_end else 0
            session.display_logout_at = display_end
            session.display_duration_hm = _format_seconds_hm(seconds)
            session.can_submit_correction = (
                session.user_id == self.request.user.id
                and (
                    (
                        session.checkout_review_status == CheckoutReviewStatus.PENDING
                        and session.requested_logout_at is None
                    )
                    or session.checkout_review_status == CheckoutReviewStatus.REJECTED
                )
            )
            session.awaiting_review = (
                session.user_id == self.request.user.id
                and session.checkout_review_status == CheckoutReviewStatus.PENDING
                and session.requested_logout_at is not None
            )
            session.can_review = (
                self.can_review_user(session.user_id)
                and session.checkout_review_status == CheckoutReviewStatus.PENDING
                and session.requested_logout_at is not None
            )
            session_rows.append(session)

        leave_rows = list(leaves.order_by("-start_date", "-created_at"))
        for leave in leave_rows:
            leave.can_review = (
                self.can_review_user(leave.user_id)
                and self.request.user.has_perm("common.review_leave_requests")
                and leave.status == LeaveStatus.PENDING
            )
            leave.can_cancel = (
                leave.user_id == self.request.user.id
                and leave.status == LeaveStatus.PENDING
            )

        summary_user_ids = {selected_id} if selected_id else visible_ids
        attendance_summary = _build_attendance_summary(
            UserLoginSession.objects.filter(user_id__in=summary_user_ids),
            date_from,
            date_to,
        )
        context.update({
            "date_from": date_from,
            "date_to": date_to,
            "employees": employees,
            "selected_user_id": selected_id,
            "session_rows": session_rows,
            "leave_rows": leave_rows,
            "leave_form": LeaveRequestForm(),
            "can_review_attendance": self.request.user.has_perm("common.review_attendance"),
            "summary": {
                "attendance_days": attendance_summary["attendance_days"],
                "pending_checkouts": sessions.filter(
                    checkout_review_status=CheckoutReviewStatus.PENDING,
                ).count(),
                "active_sessions": sessions.filter(logout_at__isnull=True).count(),
                "approved_leave_days": sum(
                    (min(leave.end_date, date_to) - max(leave.start_date, date_from)).days + 1
                    for leave in leave_rows
                    if leave.status == LeaveStatus.APPROVED
                ),
            },
        })
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

        current_user = self.request.user
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
            "show_detailed_data": user_has_role(current_user, ROLE_ADMIN),

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

            "recent_inquiries": inquiries_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "recent_leads": leads_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "recent_deals": deals_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "recent_invoices": invoices_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "recent_payments": payments_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
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

        current_user = self.request.user
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

        total_work_seconds = _sum_work_session_seconds(work_sessions_in_period)

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
            "show_detailed_data": user_has_role(current_user, ROLE_ADMIN),

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
                "total_work_hm": _format_seconds_hm(total_work_seconds),

                "completion_rate": completion_rate,
            },

            "project_status_counts": project_status_counts,
            "task_status_counts": task_status_counts,
            "deliverable_status_counts": deliverable_status_counts,
            "task_department_counts": task_department_counts,
            "deliverable_department_counts": deliverable_department_counts,

            "recent_projects": projects_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "overdue_projects": overdue_projects.order_by("due_date")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "recent_tasks": tasks_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "overdue_tasks": overdue_tasks.order_by("due_date")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "recent_deliverables": deliverables_in_period.order_by("-created_at")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
            "overdue_deliverables": overdue_deliverables.order_by("due_date")[:10] if user_has_role(current_user, ROLE_ADMIN) else [],
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

        total_work_seconds = _sum_work_session_seconds(work_sessions_in_period)
        task_work_seconds = _sum_work_session_seconds(task_work_sessions)
        deliverable_work_seconds = _sum_work_session_seconds(deliverable_work_sessions)

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

        work_by_employee_map = {}
        for session in work_sessions_in_period.select_related("user"):
            row = work_by_employee_map.setdefault(
                session.user_id,
                {
                    "user_id": session.user_id,
                    "user__username": session.user.username,
                    "user__first_name": session.user.first_name,
                    "user__last_name": session.user.last_name,
                    "session_count": 0,
                    "total_seconds": 0,
                },
            )
            row["session_count"] += 1
            row["total_seconds"] += max(int(session.live_work_seconds or 0), 0)

        work_by_employee = sorted(
            work_by_employee_map.values(),
            key=lambda row: row["total_seconds"],
            reverse=True,
        )
        for row in work_by_employee:
            seconds = row["total_seconds"]
            row["total_hours"] = round(seconds / 3600, 2)
            row["total_hm"] = _format_seconds_hm(seconds)

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

        attendance_summary = _build_attendance_summary(
            login_sessions_qs=login_sessions,
            date_from=date_from,
            date_to=date_to,
        )

        recent_work_sessions = list(work_sessions_in_period.order_by("-started_at")[:20])
        show_detailed_data = user_has_role(current_user, ROLE_ADMIN)
        if not show_detailed_data:
            login_table["rows"] = []
            recent_work_sessions = []
            work_by_employee = []

        context.update({
            "report_title": "Employee Work Report",
            "date_from": date_from,
            "date_to": date_to,
            "selected_user": selected_user,
            "selected_user_name": _user_display(selected_user),
            "employees": _employee_options_for_user(current_user),
            "pdf_download_url": self.get_pdf_url(),
            "show_detailed_data": show_detailed_data,

            "login_chart": login_chart,
            "login_table": login_table,
            "attendance_summary": attendance_summary,

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
                "attendance_days": attendance_summary["attendance_days"],
                "attendance_required_hm": attendance_summary["required_hm"],

                "total_work_seconds": total_work_seconds,
                "total_work_hours": round(total_work_seconds / 3600, 2),
                "total_work_hm": _format_seconds_hm(total_work_seconds),

                "task_work_seconds": task_work_seconds,
                "task_work_hours": round(task_work_seconds / 3600, 2),
                "task_work_hm": _format_seconds_hm(task_work_seconds),

                "deliverable_work_seconds": deliverable_work_seconds,
                "deliverable_work_hours": round(deliverable_work_seconds / 3600, 2),
                "deliverable_work_hm": _format_seconds_hm(deliverable_work_seconds),

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
            "recent_work_sessions": recent_work_sessions,
            "recent_tasks": tasks_in_period.order_by("-created_at")[:10],
            "overdue_tasks": overdue_tasks.order_by("due_date")[:10],
            "recent_deliverables": deliverables_in_period.order_by("-created_at")[:10],
            "overdue_deliverables": overdue_deliverables.order_by("due_date")[:10],
        })

        return context
