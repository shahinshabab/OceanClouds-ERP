# events/forms.py

from django import forms

from crm.models import Contact
from services.models import Service, Package, Vendor, InventoryItem

from .models import (
    Venue,
    Event,
    EventChecklist,
    ChecklistItem,
)


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            widget = field.widget
            existing_classes = widget.attrs.get("class", "")

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (existing_classes + " form-check-input").strip()

            elif isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs["class"] = existing_classes.strip()

            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (existing_classes + " form-select").strip()

            else:
                widget.attrs["class"] = (existing_classes + " form-control").strip()


class DateInput(forms.DateInput):
    input_type = "date"


class TimeInput(forms.TimeInput):
    input_type = "time"


class VenueForm(BootstrapModelForm):
    class Meta:
        model = Venue
        fields = [
            "name",
            "venue_type",
            "contact_name",
            "phone",
            "email",
            "address_line1",
            "address_line2",
            "city",
            "district",
            "state",
            "country",
            "notes",
            "is_active",
        ]

        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class EventForm(BootstrapModelForm):
    class Meta:
        model = Event
        fields = [
            "project",
            "client",
            "primary_contact",
            "name",
            "event_type",
            "status",
            "date",
            "start_time",
            "end_time",
            "venue",
            "services",
            "packages",
            "vendors",
            "inventory_items",
            "notes",
            "internal_notes",
        ]

        widgets = {
            "date": DateInput(),
            "start_time": TimeInput(),
            "end_time": TimeInput(),

            # Important: checkbox multi-select
            "services": forms.CheckboxSelectMultiple(),
            "packages": forms.CheckboxSelectMultiple(),
            "vendors": forms.CheckboxSelectMultiple(),
            "inventory_items": forms.CheckboxSelectMultiple(),

            "notes": forms.Textarea(attrs={"rows": 3}),
            "internal_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["services"].queryset = Service.objects.filter(is_active=True).order_by("name")
        self.fields["packages"].queryset = Package.objects.filter(is_active=True).order_by("name")
        self.fields["vendors"].queryset = Vendor.objects.filter(is_active=True).order_by("name")
        self.fields["inventory_items"].queryset = InventoryItem.objects.filter(is_active=True).order_by("name")
        self.fields["venue"].queryset = Venue.objects.filter(is_active=True).order_by("name")

        client_id = None

        if self.data.get("client"):
            client_id = self.data.get("client")
        elif self.instance and self.instance.client_id:
            client_id = self.instance.client_id
        elif self.initial.get("client"):
            client_id = self.initial.get("client")

        if client_id:
            self.fields["primary_contact"].queryset = Contact.objects.filter(
                client_id=client_id
            ).order_by("first_name", "last_name")
        else:
            self.fields["primary_contact"].queryset = Contact.objects.none()

        self.fields["project"].required = False
        self.fields["client"].required = False
        self.fields["primary_contact"].required = False
        self.fields["venue"].required = False
        self.fields["services"].required = False
        self.fields["packages"].required = False
        self.fields["vendors"].required = False
        self.fields["inventory_items"].required = False

    def clean(self):
        cleaned_data = super().clean()

        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        if start_time and end_time and end_time <= start_time:
            self.add_error("end_time", "End time must be after start time.")

        return cleaned_data


class EventChecklistForm(BootstrapModelForm):
    class Meta:
        model = EventChecklist
        fields = [
            "event",
            "title",
            "notes",
        ]

        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ChecklistItemForm(BootstrapModelForm):
    class Meta:
        model = ChecklistItem
        fields = [
            "checklist",
            "title",
            "category",
            "is_done",
            "due_date",
            "assigned_to",
            "notes",
        ]

        widgets = {
            "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }