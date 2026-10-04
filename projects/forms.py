# projects/forms.py

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import F

from common.forms import BootstrapModelForm
from common.roles import (
    ROLE_PROJECT_MANAGER,
    ROLE_EMPLOYEE,
    user_has_role,
)

from .models import (
    Project,
    Task,
    Deliverable,
    TaskStatus,
    DeliverableStatus,
)

User = get_user_model()


class DateInput(forms.DateInput):
    input_type = "date"


def users_in_roles(*role_names):
    return (
        User.objects.filter(is_active=True, groups__name__in=role_names)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


def assignable_users(user=None, current=None):
    """
    People who can own a task or deliverable: employees and project managers.

    The signed-in user is always included so self-managed work can be
    self-assigned, and the current assignee is kept so editing never drops it.
    """
    ids = set(
        users_in_roles(ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER).values_list("id", flat=True)
    )
    if user is not None and user.is_authenticated:
        ids.add(user.pk)
    if current is not None:
        ids.add(current.pk)
    return User.objects.filter(pk__in=ids).order_by("first_name", "last_name", "username")


class AssigneeChoiceMixin:
    """
    Labels assignees by name and marks the signed-in user as "(me)".
    """

    def setup_assignee_field(self):
        field = self.fields["assigned_to"]
        current = self.instance.assigned_to if self.instance.pk and self.instance.assigned_to_id else None
        field.queryset = assignable_users(self.user, current)
        me_id = self.user.pk if self.user is not None else None

        def label(member):
            name = member.get_full_name().strip() or member.username
            return f"{name} (me)" if member.pk == me_id else name

        field.label_from_instance = label


class ProjectForm(BootstrapModelForm):
    class Meta:
        model = Project
        fields = [
            "name",
            "client",
            "deal",
            "event",
            "project_directory",
            "description",
            "manager",
            "start_date",
            "due_date",
            "status",
            "priority",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": DateInput(),
            "due_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["client"].required = False
        self.fields["deal"].required = False
        self.fields["event"].required = False
        self.fields["project_directory"].required = False
        self.fields["manager"].required = False

        self.fields["manager"].queryset = users_in_roles(ROLE_PROJECT_MANAGER)

        if self.user and user_has_role(self.user, ROLE_PROJECT_MANAGER):
            self.fields["manager"].initial = self.user


class TaskForm(AssigneeChoiceMixin, BootstrapModelForm):
    class Meta:
        model = Task
        fields = [
            "project",
            "name",
            "department",
            "category",
            "directory",
            "count",
            "description",
            "assigned_to",
            "status",
            "priority",
            "start_date",
            "due_date",
            "estimated_minutes",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": DateInput(),
            "due_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        project = kwargs.pop("project", None)
        super().__init__(*args, **kwargs)

        self.fields["project"].queryset = Project.objects.all().order_by("-created_at")

        if project:
            self.fields["project"].required = False
            self.fields["project"].initial = project
            self.fields["project"].queryset = Project.objects.filter(pk=project.pk)

        self.setup_assignee_field()

    def clean_status(self):
        status = self.cleaned_data.get("status")

        if status == TaskStatus.IN_PROGRESS:
            assigned_to = self.cleaned_data.get("assigned_to")
            if not assigned_to:
                raise forms.ValidationError("Assign someone before moving task to In Progress.")

        return status


class DeliverableForm(AssigneeChoiceMixin, BootstrapModelForm):
    class Meta:
        model = Deliverable
        fields = [
            "project",
            "name",
            "category",
            "type",
            "department",
            "directory",
            "description",
            "assigned_to",
            "status",
            "tasks",
            "priority",
            "start_date",
            "due_date",
            "file_link",
            "file",
            "preview_link",
            "version",
            "delivery_medium",
            "quantity",
            "handed_over_to",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": DateInput(),
            "due_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.fixed_project = kwargs.pop("project", None)

        super().__init__(*args, **kwargs)

        self.fields["project"].queryset = Project.objects.all()
        self.setup_assignee_field()
        self.fields["tasks"].label_from_instance = self._task_option_label

        if self.fixed_project:
            self.fields["project"].required = False
            self.fields["project"].initial = self.fixed_project
            self.fields["tasks"].queryset = Task.objects.select_related("assigned_to").filter(
                project=self.fixed_project
            ).order_by(F("due_date").asc(nulls_last=True), "status", "priority", "created_at")
        else:
            self.fields["tasks"].queryset = Task.objects.none()

        if self.instance and self.instance.pk:
            self.fields["tasks"].queryset = Task.objects.select_related("assigned_to").filter(
                project=self.instance.project
            ).order_by(F("due_date").asc(nulls_last=True), "status", "priority", "created_at")

    @staticmethod
    def _task_option_label(task):
        assignee = "Unassigned"
        if task.assigned_to_id:
            full_name = task.assigned_to.get_full_name().strip()
            assignee = full_name or task.assigned_to.username

        return f"{task.name} ({task.get_status_display()} - {assignee})"

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        tasks = cleaned.get("tasks")

        if status in [
            DeliverableStatus.IN_PROGRESS,
            DeliverableStatus.INTERNAL_REVIEW,
            DeliverableStatus.CLIENT_REVIEW,
            DeliverableStatus.READY_TO_DELIVER,
            DeliverableStatus.DELIVERED,
        ]:
            if tasks and tasks.exists():
                if tasks.exclude(status=TaskStatus.COMPLETED).exists():
                    raise forms.ValidationError(
                        "All linked tasks must be completed before moving this deliverable forward."
                    )

        return cleaned