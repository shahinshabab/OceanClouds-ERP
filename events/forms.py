# events/forms.py

from django import forms

from common.forms import BootstrapModelForm
from services.models import Service, Package, Vendor, InventoryItem

from .models import (
    Venue,
    Event,
    EventChecklist,
    ChecklistItem,
)


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
            "client",
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
        if "vendors" in self.fields:
            self.fields["vendors"].queryset = Vendor.objects.filter(is_active=True).order_by("name")
            self.fields["inventory_items"].queryset = InventoryItem.objects.filter(is_active=True).order_by("name")
        self.fields["venue"].queryset = Venue.objects.filter(is_active=True).order_by("name")

        # Contact comes from the client and the project is created later
        # from the event. Vendors and inventory are assigned after the
        # event exists, so they only show when editing.
        if not self.instance.pk:
            del self.fields["vendors"]
            del self.fields["inventory_items"]

        self.fields["client"].required = False
        self.fields["venue"].required = False
        self.fields["services"].required = False
        self.fields["packages"].required = False
        for name in ("vendors", "inventory_items"):
            if name in self.fields:
                self.fields[name].required = False

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