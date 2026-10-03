# projects/views.py

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum, F
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    TemplateView,
)

from common.mixins import ProjectAccessMixin, ProjectWorkAccessMixin, ProjectAdminOnlyMixin
from common.roles import (
    ROLE_EMPLOYEE,
    ROLE_PROJECT_MANAGER,
)

from .forms import ProjectForm, TaskForm, DeliverableForm
from .models import (
    Project,
    Task,
    Deliverable,
    ProjectStatus,
    TaskStatus,
    DeliverableStatus,
    Priority,
    DeliverableType,
    WorkSession,
    WorkSessionStatus,
)
from .utils import (
    _form_error_message,
    _scope_tags,
    _validation_error_message,
    close_active_work_for_target,
    is_admin,
    is_admin_or_project_manager,
    is_employee,
    is_project_manager,
    user_has_active_work,
    visible_deliverables_for,
    visible_projects_for,
    visible_tasks_for,
)

User = get_user_model()


# ============================================================
# Scoped message helpers
# ============================================================

class DetailMessageScopeMixin:
    """
    Adds one message scope to detail/form pages.

    Example:
        detail_message_scope = "scope:project"

    Template can show only:
    - scope:project
    - scope:task
    - scope:deliverable
    - scope:email
    - scope:global
    """

    detail_message_scope = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["detail_message_scope"] = self.detail_message_scope
        return context


# ============================================================
# Projects
# ============================================================

class ProjectListView(ProjectAccessMixin, ListView):
    model = Project
    template_name = "projects/project_list.html"
    context_object_name = "projects"
    paginate_by = 20

    def get_queryset(self):
        qs = visible_projects_for(self.request.user)

        q = self.request.GET.get("q")
        status = self.request.GET.get("status")
        manager_id = self.request.GET.get("manager")
        priority = self.request.GET.get("priority")

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(client__name__icontains=q)
                | Q(deal__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if priority:
            qs = qs.filter(priority=priority)

        if manager_id:
            qs = qs.filter(manager_id=manager_id)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = self.request.GET.get("q", "")
        context["status_filter"] = self.request.GET.get("status", "")
        context["priority_filter"] = self.request.GET.get("priority", "")
        context["manager_filter"] = self.request.GET.get("manager", "")
        context["status_choices"] = ProjectStatus.choices
        context["priority_choices"] = Priority.choices
        context["manager_choices"] = User.objects.filter(
            is_active=True,
            groups__name=ROLE_PROJECT_MANAGER,
        ).order_by("first_name", "last_name", "username")

        return context


class ProjectDetailView(ProjectAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Project
    template_name = "projects/project_detail.html"
    context_object_name = "project"
    detail_message_scope = "scope:project"

    def get_queryset(self):
        return visible_projects_for(self.request.user).prefetch_related(
            "tasks__assigned_to",
            "deliverables__assigned_to",
            "deliverables__tasks",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object

        context["tasks"] = project.tasks.select_related("assigned_to").order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

        context["deliverables"] = project.deliverables.select_related(
            "assigned_to"
        ).prefetch_related("tasks").order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

        context["work_sessions"] = project.work_sessions.select_related(
            "user",
            "task",
            "deliverable",
        )[:20]

        return context


class ProjectOverviewView(ProjectAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Project
    template_name = "projects/project_overview.html"
    context_object_name = "project"
    detail_message_scope = "scope:project"

    def get_queryset(self):
        return visible_projects_for(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object
        deal = project.deal

        contracts_qs = []
        invoices_qs = []
        payments_qs = []
        proposals_qs = []
        invoice_total = Decimal("0.00")
        payments_total = Decimal("0.00")
        amount_due = Decimal("0.00")

        if deal:
            if hasattr(deal, "proposals"):
                proposals_qs = deal.proposals.all().order_by("-created_at")

            if hasattr(deal, "contracts"):
                contracts_qs = deal.contracts.all().annotate(
                    total_amount=Coalesce(
                        Sum("items__line_total"),
                        Decimal("0.00"),
                    )
                )

            if hasattr(deal, "invoices"):
                invoices_qs = deal.invoices.all().select_related("deal")
                invoice_ids = invoices_qs.values_list("id", flat=True)

                try:
                    from sales.models import Payment

                    payments_qs = Payment.objects.filter(
                        invoice_id__in=invoice_ids
                    ).select_related("invoice").order_by("-date", "-created_at")

                except Exception:
                    payments_qs = []

                invoice_total = invoices_qs.aggregate(
                    total=Coalesce(Sum("total"), Decimal("0.00"))
                )["total"]

                if hasattr(payments_qs, "aggregate"):
                    payments_total = payments_qs.aggregate(
                        total=Coalesce(Sum("amount"), Decimal("0.00"))
                    )["total"]

                amount_due = invoice_total - payments_total

        context.update(
            {
                "client": project.client,
                "deal": deal,
                "proposals": proposals_qs,
                "contracts": contracts_qs,
                "invoices": invoices_qs,
                "payments": payments_qs,
                "invoice_total": invoice_total,
                "payments_total": payments_total,
                "amount_due": amount_due,
                "tasks": project.tasks.select_related("assigned_to"),
                "deliverables": project.deliverables.select_related(
                    "assigned_to"
                ).prefetch_related("tasks"),
                "total_work_hours": project.total_work_hours,
            }
        )

        return context


class ProjectCreateView(ProjectAdminOnlyMixin, DetailMessageScopeMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"
    detail_message_scope = "scope:project"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Project created successfully.",
            extra_tags=_scope_tags("project"),
        )

        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            _form_error_message(
                form,
                "Project could not be saved. Please check the highlighted errors.",
            ),
            extra_tags=_scope_tags("project"),
        )

        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("projects:project_detail", args=[self.object.pk])


class ProjectUpdateView(ProjectAdminOnlyMixin, DetailMessageScopeMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"
    detail_message_scope = "scope:project"

    def get_queryset(self):
        return Project.objects.all()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Project updated successfully.",
            extra_tags=_scope_tags("project"),
        )

        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            _form_error_message(
                form,
                "Project could not be updated. Please check the highlighted errors.",
            ),
            extra_tags=_scope_tags("project"),
        )

        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("projects:project_detail", args=[self.object.pk])


class ProjectKanbanView(ProjectAccessMixin, TemplateView):
    template_name = "projects/project_kanban.html"

    def get_queryset(self):
        return visible_projects_for(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()

        context["projects_by_status"] = {
            ProjectStatus.PLANNED: qs.filter(status=ProjectStatus.PLANNED),
            ProjectStatus.ACTIVE: qs.filter(status=ProjectStatus.ACTIVE),
            ProjectStatus.COMPLETED: qs.filter(status=ProjectStatus.COMPLETED),
        }

        context["kanban_status_choices"] = [
            (ProjectStatus.PLANNED, "Planned"),
            (ProjectStatus.ACTIVE, "Active"),
            (ProjectStatus.COMPLETED, "Completed"),
        ]

        return context


class ProjectStatusUpdateView(ProjectAccessMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(visible_projects_for(request.user), pk=pk)
        new_status = request.POST.get("status")

        kanban_statuses = {
            ProjectStatus.PLANNED,
            ProjectStatus.ACTIVE,
            ProjectStatus.COMPLETED,
        }

        if new_status not in kanban_statuses:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid project status.",
                },
                status=400,
            )

        if new_status == ProjectStatus.COMPLETED and not project.can_be_completed:
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "This project cannot be completed yet. "
                        "Complete all project tasks and deliver all deliverables first."
                    ),
                },
                status=400,
            )

        if new_status == ProjectStatus.COMPLETED:
            project.completed_at = timezone.now()
        else:
            project.completed_at = None

        project.status = new_status
        project.save(update_fields=["status", "completed_at"])

        return JsonResponse(
            {
                "success": True,
                "status": new_status,
                "status_display": project.get_status_display(),
            }
        )


class ProjectCloseView(ProjectAccessMixin, View):
    """
    Close a completed project.

    Rule:
    - Project must already be completed.
    - If client is linked, client review must exist before closing.
    - If client is not linked yet, allow closing for now because client is nullable.
    """

    def post(self, request, pk):
        project = get_object_or_404(visible_projects_for(request.user), pk=pk)

        try:
            project.mark_closed()

            messages.success(
                request,
                "Project closed successfully.",
                extra_tags=_scope_tags("project"),
            )

        except ValidationError as exc:
            messages.error(
                request,
                _validation_error_message(exc),
                extra_tags=_scope_tags("project"),
            )

        next_url = request.POST.get("next") or request.GET.get("next")

        if next_url:
            return redirect(next_url)

        return redirect("projects:project_detail", pk=project.pk)


# ============================================================
# Tasks
# ============================================================

class TaskListView(ProjectWorkAccessMixin, ListView):
    model = Task
    template_name = "projects/task_list.html"
    context_object_name = "tasks"
    paginate_by = 20

    def get_queryset(self):
        qs = visible_tasks_for(self.request.user).filter(
            project__status=ProjectStatus.ACTIVE
        )

        q = self.request.GET.get("q")
        status = self.request.GET.get("status")
        priority = self.request.GET.get("priority")
        category = self.request.GET.get("category")
        department = self.request.GET.get("department")
        due = self.request.GET.get("due")
        employee_id = self.request.GET.get("employee")
        today = timezone.localdate()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(project__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if priority:
            qs = qs.filter(priority=priority)

        if category:
            qs = qs.filter(category=category)

        if department:
            qs = qs.filter(department=department)

        if employee_id and is_admin_or_project_manager(self.request.user):
            qs = qs.filter(assigned_to_id=employee_id)

        if due == "overdue":
            qs = qs.filter(due_date__lt=today).exclude(status=TaskStatus.COMPLETED)
        elif due == "today":
            qs = qs.filter(due_date=today)
        elif due == "upcoming":
            qs = qs.filter(due_date__gt=today)
        elif due == "no_due":
            qs = qs.filter(due_date__isnull=True)

        return qs.order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        from .models import TaskCategory, ProductionDepartment

        context["q"] = self.request.GET.get("q", "")
        context["status_choices"] = TaskStatus.choices
        context["priority_choices"] = Priority.choices
        context["category_choices"] = TaskCategory.choices
        context["department_choices"] = ProductionDepartment.choices

        context["status_filter"] = self.request.GET.get("status", "")
        context["priority_filter"] = self.request.GET.get("priority", "")
        context["category_filter"] = self.request.GET.get("category", "")
        context["department_filter"] = self.request.GET.get("department", "")
        context["due_filter"] = self.request.GET.get("due", "")
        context["employee_filter"] = self.request.GET.get("employee", "")

        if is_admin_or_project_manager(self.request.user):
            context["employee_choices"] = User.objects.filter(
                is_active=True,
                groups__name=ROLE_EMPLOYEE,
            ).order_by("first_name", "last_name", "username")
        else:
            context["employee_choices"] = User.objects.none()

        return context


class TaskCreateView(ProjectAccessMixin, DetailMessageScopeMixin, CreateView):
    model = Task
    form_class = TaskForm
    template_name = "projects/task_form.html"
    detail_message_scope = "scope:task"

    def dispatch(self, request, *args, **kwargs):
        self.project = None
        project_pk = self.kwargs.get("project_pk")

        if project_pk:
            self.project = get_object_or_404(
                visible_projects_for(request.user),
                pk=project_pk,
            )

            if not is_admin_or_project_manager(request.user):
                messages.error(
                    request,
                    "You are not allowed to create tasks.",
                    extra_tags=_scope_tags("project", "task"),
                )
                return redirect("projects:project_detail", pk=self.project.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user

        if self.project:
            kwargs["project"] = self.project

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = self.project
        return context

    def form_valid(self, form):
        task = form.save(commit=False)

        if self.project:
            task.project = self.project

        task.save()
        form.save_m2m()

        messages.success(
            self.request,
            "Task created successfully.",
            extra_tags=_scope_tags("task"),
        )

        return redirect("projects:task_detail", pk=task.pk)

    def form_invalid(self, form):
        messages.error(
            self.request,
            _form_error_message(
                form,
                "Task could not be saved. Please check the highlighted errors.",
            ),
            extra_tags=_scope_tags("task"),
        )
        return super().form_invalid(form)


class TaskUpdateView(ProjectAccessMixin, DetailMessageScopeMixin, UpdateView):
    model = Task
    form_class = TaskForm
    template_name = "projects/task_form.html"
    detail_message_scope = "scope:task"

    def get_queryset(self):
        user = self.request.user
        qs = Task.objects.select_related(
            "project",
            "assigned_to",
            "project__manager",
        )

        if is_admin(user):
            return qs

        if is_project_manager(user):
            return qs.filter(project__manager=user)

        return Task.objects.none()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["project"] = self.object.project
        return kwargs

    def form_valid(self, form):
        old = self.get_object()
        task = form.save(commit=False)

        # Keep original project during edit.
        task.project = old.project

        if old.status == TaskStatus.IN_PROGRESS and task.status != TaskStatus.IN_PROGRESS:
            close_active_work_for_target(
                task.assigned_to or self.request.user,
                task=task,
            )

        if task.status == TaskStatus.COMPLETED and not task.completed_at:
            task.completed_at = timezone.now()

        task.save()
        form.save_m2m()

        messages.success(
            self.request,
            "Task updated successfully.",
            extra_tags=_scope_tags("task"),
        )

        return redirect("projects:task_detail", pk=task.pk)

    def form_invalid(self, form):
        messages.error(
            self.request,
            _form_error_message(
                form,
                "Task could not be updated. Please check the highlighted errors.",
            ),
            extra_tags=_scope_tags("task"),
        )
        return super().form_invalid(form)


class TaskDetailView(ProjectWorkAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Task
    template_name = "projects/task_detail.html"
    context_object_name = "task"
    detail_message_scope = "scope:task"

    def get_queryset(self):
        return visible_tasks_for(self.request.user).prefetch_related("deliverables")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["active_work_session"] = WorkSession.objects.filter(
            task=self.object,
            status__in=[
                WorkSessionStatus.ACTIVE,
                WorkSessionStatus.PAUSED,
            ],
        ).select_related("user").first()

        context["work_sessions"] = self.object.work_sessions.select_related("user")[:20]

        return context


class TaskKanbanView(ProjectWorkAccessMixin, TemplateView):
    template_name = "projects/task_kanban.html"

    def get_queryset(self):
        return (
            visible_tasks_for(self.request.user)
            .filter(project__status=ProjectStatus.ACTIVE)
            .select_related("project", "assigned_to")
            .prefetch_related("deliverables")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()

        pending_tasks = qs.filter(
            status=TaskStatus.PENDING
        ).order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

        in_progress_tasks = qs.filter(
            status__in=[
                TaskStatus.IN_PROGRESS,
                TaskStatus.PAUSED,
            ]
        ).order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

        completed_tasks = qs.filter(
            status=TaskStatus.COMPLETED
        ).order_by(
            F("completed_at").desc(nulls_last=True),
            "-created_at",
        )

        context["tasks_by_status"] = {
            "pending": pending_tasks,
            "in_progress": in_progress_tasks,
            "completed": completed_tasks,
        }

        context["kanban_status_choices"] = [
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
        ]

        return context


class TaskStatusUpdateView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(visible_tasks_for(request.user), pk=pk)

        new_status = request.POST.get("status")
        old_status = task.status
        user = request.user

        valid = {key for key, _ in TaskStatus.choices}

        if new_status not in valid:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid task status.",
                },
                status=400,
            )

        if is_employee(user) and task.assigned_to_id != user.id:
            return JsonResponse(
                {
                    "success": False,
                    "error": "This task is not assigned to you.",
                },
                status=403,
            )

        work_user = task.assigned_to or user

        # Start / Continue
        if new_status == TaskStatus.IN_PROGRESS:
            paused_session = WorkSession.objects.filter(
                user=work_user,
                task=task,
                status=WorkSessionStatus.PAUSED,
            ).first()

            if paused_session:
                if WorkSession.objects.filter(
                    user=work_user,
                    status=WorkSessionStatus.ACTIVE,
                ).exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "This employee already has another active work item.",
                        },
                        status=400,
                    )

                paused_session.resume()

            elif old_status != TaskStatus.IN_PROGRESS:
                if WorkSession.objects.filter(
                    user=work_user,
                    status=WorkSessionStatus.ACTIVE,
                ).exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "This employee already has another active work item.",
                        },
                        status=400,
                    )

                if not task.first_started_at:
                    task.first_started_at = timezone.now()

                WorkSession.objects.create(
                    user=work_user,
                    project=task.project,
                    task=task,
                    started_at=timezone.now(),
                    last_resumed_at=timezone.now(),
                )

        # Pause
        if new_status == TaskStatus.PAUSED:
            session = WorkSession.objects.filter(
                user=work_user,
                task=task,
                status=WorkSessionStatus.ACTIVE,
            ).first()

            if session:
                session.pause()

        # Leaving active/paused to another final/review state
        if new_status not in [
            TaskStatus.IN_PROGRESS,
            TaskStatus.PAUSED,
        ]:
            sessions = WorkSession.objects.filter(
                user=work_user,
                task=task,
                status__in=[
                    WorkSessionStatus.ACTIVE,
                    WorkSessionStatus.PAUSED,
                ],
            )

            for session in sessions:
                session.end()

        if new_status == TaskStatus.COMPLETED and not task.completed_at:
            task.completed_at = timezone.now()

        task.status = new_status
        task.save(update_fields=["status", "first_started_at", "completed_at"])

        return JsonResponse(
            {
                "success": True,
                "status": new_status,
                "status_display": task.get_status_display(),
            }
        )


# ============================================================
# Deliverables
# ============================================================

class DeliverableListView(ProjectWorkAccessMixin, ListView):
    model = Deliverable
    template_name = "projects/deliverable_list.html"
    context_object_name = "deliverables"
    paginate_by = 20

    def get_queryset(self):
        qs = visible_deliverables_for(self.request.user).filter(
            project__status=ProjectStatus.ACTIVE
        )

        q = self.request.GET.get("q")
        status = self.request.GET.get("status")
        category = self.request.GET.get("category")
        d_type = self.request.GET.get("type")
        priority = self.request.GET.get("priority")
        employee_id = self.request.GET.get("employee")

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(project__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if category:
            qs = qs.filter(category=category)

        if d_type:
            qs = qs.filter(type=d_type)

        if priority:
            qs = qs.filter(priority=priority)

        if employee_id and is_admin_or_project_manager(self.request.user):
            qs = qs.filter(assigned_to_id=employee_id)

        return qs.order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        from .models import DeliverableCategory

        context["q"] = self.request.GET.get("q", "")
        context["status_choices"] = DeliverableStatus.choices
        context["category_choices"] = DeliverableCategory.choices
        context["type_choices"] = DeliverableType.choices
        context["priority_choices"] = Priority.choices

        context["status_filter"] = self.request.GET.get("status", "")
        context["category_filter"] = self.request.GET.get("category", "")
        context["type_filter"] = self.request.GET.get("type", "")
        context["priority_filter"] = self.request.GET.get("priority", "")
        context["employee_filter"] = self.request.GET.get("employee", "")

        if is_admin_or_project_manager(self.request.user):
            context["employee_choices"] = User.objects.filter(
                is_active=True,
                groups__name=ROLE_EMPLOYEE,
            ).order_by("first_name", "last_name", "username")
        else:
            context["employee_choices"] = User.objects.none()

        return context


class DeliverableCreateView(ProjectAccessMixin, DetailMessageScopeMixin, CreateView):
    model = Deliverable
    form_class = DeliverableForm
    template_name = "projects/deliverable_form.html"
    detail_message_scope = "scope:deliverable"

    def dispatch(self, request, *args, **kwargs):
        self.project = None
        project_pk = self.kwargs.get("project_pk")

        if project_pk:
            self.project = get_object_or_404(
                visible_projects_for(request.user),
                pk=project_pk,
            )

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user

        if self.project:
            kwargs["project"] = self.project

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = self.project
        return context

    def form_valid(self, form):
        deliverable = form.save(commit=False)

        if self.project:
            deliverable.project = self.project

        if not deliverable.assigned_to and deliverable.project.manager:
            deliverable.assigned_to = deliverable.project.manager

        deliverable.save()
        form.save_m2m()

        messages.success(
            self.request,
            "Deliverable created successfully.",
            extra_tags=_scope_tags("deliverable"),
        )

        return redirect("projects:deliverable_detail", pk=deliverable.pk)

    def form_invalid(self, form):
        messages.error(
            self.request,
            _form_error_message(
                form,
                "Deliverable could not be saved. Please check the highlighted errors.",
            ),
            extra_tags=_scope_tags("deliverable"),
        )
        return super().form_invalid(form)


class DeliverableUpdateView(ProjectAccessMixin, DetailMessageScopeMixin, UpdateView):
    model = Deliverable
    form_class = DeliverableForm
    template_name = "projects/deliverable_form.html"
    detail_message_scope = "scope:deliverable"

    def get_queryset(self):
        user = self.request.user
        qs = Deliverable.objects.select_related(
            "project",
            "assigned_to",
            "project__manager",
        )

        if is_admin(user):
            return qs

        if is_project_manager(user):
            return qs.filter(project__manager=user)

        return Deliverable.objects.none()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["project"] = self.object.project
        return kwargs

    def form_valid(self, form):
        old = self.get_object()
        deliverable = form.save(commit=False)

        # Keep original project during edit.
        deliverable.project = old.project

        if old.status == DeliverableStatus.IN_PROGRESS and deliverable.status != DeliverableStatus.IN_PROGRESS:
            close_active_work_for_target(
                deliverable.assigned_to or self.request.user,
                deliverable=deliverable,
            )

        if deliverable.status == DeliverableStatus.READY_TO_DELIVER and not deliverable.ready_at:
            deliverable.ready_at = timezone.now()

        if deliverable.status == DeliverableStatus.DELIVERED and not deliverable.delivered_at:
            deliverable.delivered_at = timezone.now()

        deliverable.save()
        form.save_m2m()

        messages.success(
            self.request,
            "Deliverable updated successfully.",
            extra_tags=_scope_tags("deliverable"),
        )

        return redirect("projects:deliverable_detail", pk=deliverable.pk)

    def form_invalid(self, form):
        messages.error(
            self.request,
            _form_error_message(
                form,
                "Deliverable could not be updated. Please check the highlighted errors.",
            ),
            extra_tags=_scope_tags("deliverable"),
        )
        return super().form_invalid(form)


class DeliverableDetailView(ProjectWorkAccessMixin, DetailMessageScopeMixin, DetailView):
    model = Deliverable
    template_name = "projects/deliverable_detail.html"
    context_object_name = "deliverable"
    detail_message_scope = "scope:deliverable"

    def get_queryset(self):
        return visible_deliverables_for(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["active_work_session"] = WorkSession.objects.filter(
            deliverable=self.object,
            status__in=[
                WorkSessionStatus.ACTIVE,
                WorkSessionStatus.PAUSED,
            ],
        ).select_related("user").first()

        context["work_sessions"] = self.object.work_sessions.select_related("user")[:20]

        return context


class DeliverableKanbanView(ProjectWorkAccessMixin, TemplateView):
    template_name = "projects/deliverable_kanban.html"

    def get_queryset(self):
        return (
            visible_deliverables_for(self.request.user)
            .filter(project__status=ProjectStatus.ACTIVE)
            .select_related("project", "assigned_to")
            .prefetch_related("tasks")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()

        pending_deliverables = qs.filter(
            status__in=[
                DeliverableStatus.PENDING,
                DeliverableStatus.WAITING_FOR_TASKS,
            ]
        ).order_by(
            F("due_date").asc(nulls_last=True),
            "priority",
            "created_at",
        )

        in_progress_deliverables = qs.filter(
            status__in=[
                DeliverableStatus.IN_PROGRESS,
                DeliverableStatus.PAUSED,
            ]
        ).order_by(
            F("due_date").asc(nulls_last=True),
            "priority",
            "created_at",
        )

        delivered_deliverables = qs.filter(
            status=DeliverableStatus.DELIVERED
        ).order_by(
            F("delivered_at").desc(nulls_last=True),
            "-created_at",
        )

        context["deliverables_by_status"] = {
            "pending": pending_deliverables,
            "in_progress": in_progress_deliverables,
            "delivered": delivered_deliverables,
        }

        context["kanban_status_choices"] = [
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("delivered", "Delivered"),
        ]

        return context


class DeliverableStatusUpdateView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        deliverable = get_object_or_404(
            visible_deliverables_for(request.user),
            pk=pk,
        )

        new_status = request.POST.get("status")
        old_status = deliverable.status
        user = request.user

        valid = {key for key, _ in DeliverableStatus.choices}

        if new_status not in valid:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Invalid deliverable status.",
                },
                status=400,
            )

        if is_employee(user) and deliverable.assigned_to_id != user.id:
            return JsonResponse(
                {
                    "success": False,
                    "error": "This deliverable is not assigned to you.",
                },
                status=403,
            )

        if new_status in [
            DeliverableStatus.IN_PROGRESS,
            DeliverableStatus.CLIENT_REVIEW,
            DeliverableStatus.INTERNAL_REVIEW,
            DeliverableStatus.READY_TO_DELIVER,
            DeliverableStatus.DELIVERED,
        ]:
            if not deliverable.required_tasks_completed:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Complete all linked tasks before moving this deliverable forward.",
                    },
                    status=400,
                )

        work_user = deliverable.assigned_to or user

        # Start / Continue
        if new_status == DeliverableStatus.IN_PROGRESS:
            paused_session = WorkSession.objects.filter(
                user=work_user,
                deliverable=deliverable,
                status=WorkSessionStatus.PAUSED,
            ).first()

            if paused_session:
                if WorkSession.objects.filter(
                    user=work_user,
                    status=WorkSessionStatus.ACTIVE,
                ).exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "This employee already has another active work item.",
                        },
                        status=400,
                    )

                paused_session.resume()

            elif old_status != DeliverableStatus.IN_PROGRESS:
                if WorkSession.objects.filter(
                    user=work_user,
                    status=WorkSessionStatus.ACTIVE,
                ).exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "This employee already has another active work item.",
                        },
                        status=400,
                    )

                if not deliverable.first_started_at:
                    deliverable.first_started_at = timezone.now()

                WorkSession.objects.create(
                    user=work_user,
                    project=deliverable.project,
                    deliverable=deliverable,
                    started_at=timezone.now(),
                    last_resumed_at=timezone.now(),
                )

        # Pause
        if new_status == DeliverableStatus.PAUSED:
            session = WorkSession.objects.filter(
                user=work_user,
                deliverable=deliverable,
                status=WorkSessionStatus.ACTIVE,
            ).first()

            if session:
                session.pause()

        # Leaving active/paused to another state
        if new_status not in [
            DeliverableStatus.IN_PROGRESS,
            DeliverableStatus.PAUSED,
        ]:
            sessions = WorkSession.objects.filter(
                user=work_user,
                deliverable=deliverable,
                status__in=[
                    WorkSessionStatus.ACTIVE,
                    WorkSessionStatus.PAUSED,
                ],
            )

            for session in sessions:
                session.end()

        if new_status == DeliverableStatus.READY_TO_DELIVER and not deliverable.ready_at:
            deliverable.ready_at = timezone.now()

        if new_status == DeliverableStatus.DELIVERED and not deliverable.delivered_at:
            deliverable.delivered_at = timezone.now()

        deliverable.status = new_status
        deliverable.save(
            update_fields=[
                "status",
                "first_started_at",
                "ready_at",
                "delivered_at",
            ]
        )

        return JsonResponse(
            {
                "success": True,
                "status": new_status,
                "status_display": deliverable.get_status_display(),
            }
        )


# ============================================================
# Work session views
# ============================================================

class StartTaskWorkView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(visible_tasks_for(request.user), pk=pk)

        if is_employee(request.user) and task.assigned_to_id != request.user.id:
            messages.error(
                request,
                "This task is not assigned to you.",
                extra_tags=_scope_tags("task"),
            )
            return redirect("projects:task_detail", pk=task.pk)

        work_user = task.assigned_to or request.user

        if user_has_active_work(work_user):
            messages.error(
                request,
                "This employee already has another active work item.",
                extra_tags=_scope_tags("task"),
            )
            return redirect("projects:task_detail", pk=task.pk)

        if not task.first_started_at:
            task.first_started_at = timezone.now()

        task.status = TaskStatus.IN_PROGRESS
        task.save(update_fields=["status", "first_started_at"])

        WorkSession.objects.create(
            user=work_user,
            project=task.project,
            task=task,
            started_at=timezone.now(),
            last_resumed_at=timezone.now(),
        )

        messages.success(
            request,
            "Task work started.",
            extra_tags=_scope_tags("task"),
        )

        return redirect("projects:task_detail", pk=task.pk)


class StartDeliverableWorkView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        deliverable = get_object_or_404(
            visible_deliverables_for(request.user),
            pk=pk,
        )

        if is_employee(request.user) and deliverable.assigned_to_id != request.user.id:
            messages.error(
                request,
                "This deliverable is not assigned to you.",
                extra_tags=_scope_tags("deliverable"),
            )
            return redirect("projects:deliverable_detail", pk=deliverable.pk)

        if not deliverable.required_tasks_completed:
            messages.error(
                request,
                "Complete linked tasks before starting this deliverable.",
                extra_tags=_scope_tags("deliverable"),
            )
            return redirect("projects:deliverable_detail", pk=deliverable.pk)

        work_user = deliverable.assigned_to or request.user

        if user_has_active_work(work_user):
            messages.error(
                request,
                "This employee already has another active work item.",
                extra_tags=_scope_tags("deliverable"),
            )
            return redirect("projects:deliverable_detail", pk=deliverable.pk)

        if not deliverable.first_started_at:
            deliverable.first_started_at = timezone.now()

        deliverable.status = DeliverableStatus.IN_PROGRESS
        deliverable.save(update_fields=["status", "first_started_at"])

        WorkSession.objects.create(
            user=work_user,
            project=deliverable.project,
            deliverable=deliverable,
            started_at=timezone.now(),
            last_resumed_at=timezone.now(),
        )

        messages.success(
            request,
            "Deliverable work started.",
            extra_tags=_scope_tags("deliverable"),
        )

        return redirect("projects:deliverable_detail", pk=deliverable.pk)


class PauseWorkSessionView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(WorkSession, pk=pk)

        if not is_admin_or_project_manager(request.user) and session.user_id != request.user.id:
            messages.error(
                request,
                "Not allowed.",
                extra_tags=_scope_tags("task", "deliverable"),
            )
            return redirect("projects:work_in_progress")

        session.pause()

        if session.task:
            session.task.status = TaskStatus.PAUSED
            session.task.save(update_fields=["status"])

            messages.info(
                request,
                "Task work paused.",
                extra_tags=_scope_tags("task"),
            )

            return redirect("projects:task_detail", pk=session.task.pk)

        session.deliverable.status = DeliverableStatus.PAUSED
        session.deliverable.save(update_fields=["status"])

        messages.info(
            request,
            "Deliverable work paused.",
            extra_tags=_scope_tags("deliverable"),
        )

        return redirect("projects:deliverable_detail", pk=session.deliverable.pk)


class ResumeWorkSessionView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(WorkSession, pk=pk)

        if not is_admin_or_project_manager(request.user) and session.user_id != request.user.id:
            messages.error(
                request,
                "Not allowed.",
                extra_tags=_scope_tags("task", "deliverable"),
            )
            return redirect("projects:work_in_progress")

        if user_has_active_work(session.user):
            messages.error(
                request,
                "This employee already has another active work item.",
                extra_tags=_scope_tags("task", "deliverable"),
            )
            return redirect("projects:work_in_progress")

        session.resume()

        if session.task:
            session.task.status = TaskStatus.IN_PROGRESS
            session.task.save(update_fields=["status"])

            messages.success(
                request,
                "Task work resumed.",
                extra_tags=_scope_tags("task"),
            )

            return redirect("projects:task_detail", pk=session.task.pk)

        session.deliverable.status = DeliverableStatus.IN_PROGRESS
        session.deliverable.save(update_fields=["status"])

        messages.success(
            request,
            "Deliverable work resumed.",
            extra_tags=_scope_tags("deliverable"),
        )

        return redirect("projects:deliverable_detail", pk=session.deliverable.pk)


class EndWorkSessionView(ProjectWorkAccessMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(WorkSession, pk=pk)

        if not is_admin_or_project_manager(request.user) and session.user_id != request.user.id:
            messages.error(
                request,
                "Not allowed.",
                extra_tags=_scope_tags("task", "deliverable"),
            )
            return redirect("projects:work_in_progress")

        session.end()

        if session.task:
            messages.success(
                request,
                "Task work session ended.",
                extra_tags=_scope_tags("task"),
            )
            return redirect("projects:task_detail", pk=session.task.pk)

        messages.success(
            request,
            "Deliverable work session ended.",
            extra_tags=_scope_tags("deliverable"),
        )

        return redirect("projects:deliverable_detail", pk=session.deliverable.pk)


class WorkInProgressView(ProjectWorkAccessMixin, ListView):
    model = WorkSession
    template_name = "projects/work_in_progress.html"
    context_object_name = "work_sessions"

    def get_queryset(self):
        qs = WorkSession.objects.select_related(
            "user",
            "project",
            "task",
            "deliverable",
        ).filter(
            status__in=[
                WorkSessionStatus.ACTIVE,
                WorkSessionStatus.PAUSED,
            ]
        )

        user = self.request.user

        if is_admin(user):
            return qs

        if is_project_manager(user):
            return qs.filter(project__manager=user)

        if is_employee(user):
            return qs.filter(user=user)

        return WorkSession.objects.none()


# ============================================================
# AJAX
# ============================================================

@login_required
def ajax_load_tasks(request):
    project_id = request.GET.get("project")
    qs = Task.objects.none()

    if project_id:
        qs = visible_tasks_for(request.user).filter(
            project_id=project_id,
        ).order_by(
            F("due_date").asc(nulls_last=True),
            "status",
            "priority",
            "created_at",
        )

    data = [
        {
            "id": task.id,
            "name": task.name,
            "status": task.status,
            "category": task.category,
        }
        for task in qs
    ]

    return JsonResponse(data, safe=False)
