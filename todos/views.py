# todos/views.py

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from common.http import safe_next_url
from common.mixins import RolesRequiredMixin
from common.roles import (
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
    user_has_role,
)

from todos.forms import TodoForm
from todos.models import Todo, TodoStatus


TODO_ACCESS_ROLES = [
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
]


class TodoAccessMixin(RolesRequiredMixin):
    allowed_roles = TODO_ACCESS_ROLES


class TodoQuerysetMixin:
    model = Todo

    def get_queryset(self):
        user = self.request.user

        qs = (
            Todo.objects
            .select_related(
                "owner",
                "assigned_to",
                "project",
                "task",
                "deliverable",
                "client",
                "lead",
                "deal",
                "proposal",
                "contract",
                "invoice",
            )
        )

        # Admin sees all.
        if user_has_role(user, ROLE_ADMIN):
            return qs

        # Managers see todos they own or assigned to them.
        # They also see todos connected to their managed projects.
        if user_has_role(user, ROLE_PROJECT_MANAGER):
            return qs.filter(
                Q(owner=user) |
                Q(assigned_to=user) |
                Q(project__manager=user) |
                Q(task__project__manager=user) |
                Q(deliverable__project__manager=user)
            ).distinct()

        # CRM Manager sees todos they own or assigned to them.
        if user_has_role(user, ROLE_CRM_MANAGER):
            return qs.filter(
                Q(owner=user) |
                Q(assigned_to=user)
            ).distinct()

        # Employee sees own assigned/created todos only.
        return qs.filter(
            Q(owner=user) |
            Q(assigned_to=user)
        ).distinct()


class TodoListView(TodoAccessMixin, TodoQuerysetMixin, ListView):
    template_name = "todos/todo_list.html"
    context_object_name = "todos"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset()

        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        priority = (self.request.GET.get("priority") or "").strip()
        assigned = (self.request.GET.get("assigned") or "").strip()
        due = (self.request.GET.get("due") or "").strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(project__name__icontains=q) |
                Q(task__name__icontains=q) |
                Q(deliverable__name__icontains=q) |
                Q(client__name__icontains=q) |
                Q(lead__name__icontains=q) |
                Q(deal__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if priority:
            qs = qs.filter(priority=priority)

        if assigned == "me":
            qs = qs.filter(assigned_to=self.request.user)

        if due == "today":
            qs = qs.filter(due_date=timezone.localdate())

        elif due == "overdue":
            qs = qs.filter(
                due_date__lt=timezone.localdate()
            ).exclude(
                status__in=[
                    TodoStatus.COMPLETED,
                    TodoStatus.CANCELLED,
                ]
            )

        elif due == "upcoming":
            qs = qs.filter(
                due_date__gte=timezone.localdate()
            ).exclude(
                status__in=[
                    TodoStatus.COMPLETED,
                    TodoStatus.CANCELLED,
                ]
            )

        return qs.order_by("status", "due_date", "-priority", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        base_qs = super().get_queryset()
        today = timezone.localdate()

        context.update({
            "q": self.request.GET.get("q", ""),
            "selected_status": self.request.GET.get("status", ""),
            "selected_priority": self.request.GET.get("priority", ""),
            "selected_assigned": self.request.GET.get("assigned", ""),
            "selected_due": self.request.GET.get("due", ""),

            "status_choices": TodoStatus.choices,
            "priority_choices": Todo._meta.get_field("priority").choices,

            "summary": {
                "total": base_qs.count(),
                "pending": base_qs.filter(status=TodoStatus.PENDING).count(),
                "in_progress": base_qs.filter(status=TodoStatus.IN_PROGRESS).count(),
                "completed": base_qs.filter(status=TodoStatus.COMPLETED).count(),
                "overdue": base_qs.filter(
                    due_date__lt=today
                ).exclude(
                    status__in=[
                        TodoStatus.COMPLETED,
                        TodoStatus.CANCELLED,
                    ]
                ).count(),
                "today": base_qs.filter(due_date=today).count(),
            },
        })

        return context


class TodoDetailView(TodoAccessMixin, TodoQuerysetMixin, DetailView):
    template_name = "todos/todo_detail.html"
    context_object_name = "todo"


class TodoCreateView(TodoAccessMixin, CreateView):
    model = Todo
    form_class = TodoForm
    template_name = "todos/todo_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        todo = form.save(commit=False)
        todo.owner = self.request.user

        if not todo.assigned_to:
            todo.assigned_to = self.request.user

        todo.save()
        form.save_m2m()

        messages.success(self.request, "To-do created successfully.")
        return redirect(todo.get_absolute_url())


class TodoUpdateView(TodoAccessMixin, TodoQuerysetMixin, UpdateView):
    form_class = TodoForm
    template_name = "todos/todo_form.html"
    context_object_name = "todo"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        todo = form.save(commit=False)

        if todo.status == TodoStatus.COMPLETED and not todo.completed_at:
            todo.completed_at = timezone.now()

        if todo.status != TodoStatus.COMPLETED:
            todo.completed_at = None

        todo.save()
        form.save_m2m()

        messages.success(self.request, "To-do updated successfully.")
        return redirect(todo.get_absolute_url())


class TodoDeleteView(TodoAccessMixin, TodoQuerysetMixin, DeleteView):
    template_name = "todos/todo_confirm_delete.html"
    context_object_name = "todo"
    success_url = reverse_lazy("todos:todo_list")

    def get_queryset(self):
        qs = super().get_queryset()
        # Employees may delete only the to-dos they created themselves, not
        # ones a manager or the system assigned to them.
        if not user_has_role(self.request.user, ROLE_ADMIN, ROLE_CRM_MANAGER, ROLE_PROJECT_MANAGER):
            qs = qs.filter(owner=self.request.user)
        return qs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "To-do deleted successfully.")
        return response


class TodoCompleteView(TodoAccessMixin, TodoQuerysetMixin, View):
    def post(self, request, *args, **kwargs):
        todo = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        todo.mark_completed()
        messages.success(request, "To-do marked as completed.")
        return redirect(
            safe_next_url(request, request.META.get("HTTP_REFERER"), todo.get_absolute_url())
        )


class TodoReopenView(TodoAccessMixin, TodoQuerysetMixin, View):
    def post(self, request, *args, **kwargs):
        todo = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        todo.reopen()
        messages.success(request, "To-do reopened.")
        return redirect(
            safe_next_url(request, request.META.get("HTTP_REFERER"), todo.get_absolute_url())
        )


class TodoCancelView(TodoAccessMixin, TodoQuerysetMixin, View):
    def post(self, request, *args, **kwargs):
        todo = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        todo.cancel()
        messages.success(request, "To-do cancelled.")
        return redirect(
            safe_next_url(request, request.META.get("HTTP_REFERER"), todo.get_absolute_url())
        )