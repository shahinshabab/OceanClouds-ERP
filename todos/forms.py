# todos/forms.py

from django import forms
from django.contrib.auth import get_user_model

from django.db.models import Q

from common.forms import BootstrapModelForm
from common.roles import can_access_crm, can_access_sales, can_manage_events
from projects.models import Project
from projects.utils import (
    is_admin_or_project_manager,
    visible_deliverables_for,
    visible_tasks_for,
)
from todos.models import Todo


User = get_user_model()


class DateInput(forms.DateInput):
    input_type = "date"


class TodoForm(BootstrapModelForm):
    class Meta:
        model = Todo
        fields = [
            "title",
            "description",
            "assigned_to",
            "status",
            "priority",
            "due_date",

            # Project links
            "project",
            "task",
            "deliverable",

            # CRM links
            "client",
            "lead",

            # Sales links
            "deal",
            "proposal",
            "contract",
            "invoice",

            # Event links
            "event",
            "checklist_item",
        ]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "due_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Main optional fields
        self.fields["assigned_to"].required = False
        self.fields["due_date"].required = False

        # Optional linked records
        optional_link_fields = [
            "project",
            "task",
            "deliverable",
            "client",
            "lead",
            "deal",
            "proposal",
            "contract",
            "invoice",
            "event",
            "checklist_item",
        ]

        for field_name in optional_link_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False

        self.fields["assigned_to"].queryset = (
            User.objects
            .filter(is_active=True)
            .order_by("first_name", "last_name", "username")
        )

        self.fields["title"].widget.attrs.update({
            "placeholder": "e.g. Follow up client, Check delivery files, Call editor"
        })

        self.fields["description"].widget.attrs.update({
            "placeholder": "Optional notes about this to-do"
        })

        # Better empty labels for dropdowns
        dropdown_empty_labels = {
            "assigned_to": "Select user",
            "project": "Select project",
            "task": "Select task",
            "deliverable": "Select deliverable",
            "client": "Select client",
            "lead": "Select lead",
            "deal": "Select deal",
            "proposal": "Select proposal",
            "contract": "Select contract",
            "invoice": "Select invoice",
            "event": "Select event",
            "checklist_item": "Select checklist item",
        }

        for field_name, label in dropdown_empty_labels.items():
            if field_name in self.fields:
                self.fields[field_name].empty_label = label

        if self.user is not None:
            self._limit_links_to_user()

    def _limit_links_to_user(self):
        """
        Only offer records the user may see. A link already saved on the
        to-do stays selectable so editing never drops it.
        """
        user = self.user
        sales_ok = can_access_sales(user)
        crm_ok = can_access_crm(user)
        events_ok = can_manage_events(user)

        tasks = visible_tasks_for(user)
        deliverables = visible_deliverables_for(user)
        if is_admin_or_project_manager(user):
            projects = Project.objects.all()
        else:
            projects = Project.objects.filter(
                Q(pk__in=tasks.values("project_id"))
                | Q(pk__in=deliverables.values("project_id"))
            )

        allowed = {
            "project": projects.select_related("client"),
            "task": tasks,
            "deliverable": deliverables,
            "client": None if crm_ok else "none",
            "lead": None if crm_ok else "none",
            "deal": None if sales_ok else "none",
            "proposal": None if sales_ok else "none",
            "contract": None if sales_ok else "none",
            "invoice": None if sales_ok else "none",
            "event": None if events_ok else "none",
            "checklist_item": None if events_ok else "none",
        }

        for field_name, queryset in allowed.items():
            field = self.fields.get(field_name)
            if field is None or queryset is None:
                continue
            model = field.queryset.model
            if isinstance(queryset, str):
                queryset = model.objects.none()
            current_id = getattr(self.instance, f"{field_name}_id", None)
            if current_id:
                queryset = queryset | model.objects.filter(pk=current_id)
            field.queryset = queryset