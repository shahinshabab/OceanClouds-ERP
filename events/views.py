from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
    TemplateView,
)

from common.mixins import EventManageMixin, EventCalendarAccessMixin
from common.roles import can_manage_events
from crm.models import Client
from .models import (
    Venue,
    Event,
    EventChecklist,
    ChecklistItem,
    EventType,
    EventStatus,
    VenueType,
)

from .forms import (
    VenueForm,
    EventForm,
    EventChecklistForm,
    ChecklistItemForm,
)


# -------------------------------------------------------------------
# Common Delete Mixin
# -------------------------------------------------------------------

class EventCommonDeleteMixin(EventManageMixin, DeleteView):
    """
    Common delete view for events app.

    Template:
    events/confirm_delete.html

    Access:
    Admin + CRM Manager + Project Manager
    """

    template_name = "events/confirm_delete.html"
    object_type = "item"
    success_message = "Item deleted successfully."
    warning_message = ""
    cancel_url_name = None

    def get_object_label(self):
        return str(self.object)

    def get_cancel_url(self):
        if self.cancel_url_name:
            return reverse(self.cancel_url_name)
        return self.get_success_url()

    def get_related_counts(self):
        return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["object_type"] = self.object_type
        context["object_label"] = self.get_object_label()
        context["warning_message"] = self.warning_message
        context["related_counts"] = self.get_related_counts()
        context["cancel_url"] = self.get_cancel_url()

        return context

    def form_valid(self, form):
        messages.success(self.request, self.success_message)
        return super().form_valid(form)


# -------------------------------------------------------------------
# Calendar
# -------------------------------------------------------------------

class EventCalendarView(EventCalendarAccessMixin, TemplateView):
    """
    Everyone can access this page.
    Non-managers only see the calendar, not event details.

    Month, week and agenda views. The fill of each entry shows the event
    status (see EVENT_TONES); cancelled events are hidden unless asked for.
    """

    template_name = "events/event_calendar.html"

    EVENT_TONES = {
        EventStatus.CONFIRMED: "solid",
        EventStatus.IN_PROGRESS: "gray",
        EventStatus.PLANNED: "outline",
        EventStatus.DRAFT: "dashed",
        EventStatus.COMPLETED: "soft",
        EventStatus.CANCELLED: "danger",
    }

    def get_context_data(self, **kwargs):
        from ui.calendar import CalendarRange
        from ui.templatetags.ui_tags import status_tone

        context = super().get_context_data(**kwargs)
        request = self.request

        event_type = (request.GET.get("event_type") or "").strip()
        status = (request.GET.get("status") or "").strip()
        venue = (request.GET.get("venue") or "").strip()

        cal = CalendarRange.from_request(request, keep=("event_type", "status", "venue"))

        qs = (
            Event.objects
            .filter(date__range=(cal.start, cal.end))
            .select_related("client", "project", "venue")
            .order_by("date", "start_time", "name")
        )

        if status:
            qs = qs.filter(status=status)
        else:
            qs = qs.exclude(status=EventStatus.CANCELLED)

        if event_type:
            qs = qs.filter(event_type=event_type)

        if venue.isdigit():
            qs = qs.filter(venue_id=venue)

        can_open = can_manage_events(request.user)
        entries = []
        for event in qs:
            meta = []
            if event.client_id:
                meta.append(("bi-person", str(event.client)))
            if event.venue_id:
                meta.append(("bi-geo-alt", event.venue.name))
            meta.append(("bi-tag", event.get_event_type_display()))
            entries.append({
                "date": event.date,
                "start": event.start_time,
                "end": event.end_time,
                "title": event.name,
                "url": reverse("events:event_detail", args=[event.pk]) if can_open else "",
                "tone": self.EVENT_TONES.get(event.status, "outline"),
                "icon": "",
                "meta": meta,
                "status": event.get_status_display(),
                "status_tone": status_tone(event.status),
            })

        context.update(cal.layout(entries))
        context.update(
            {
                "event_type": event_type,
                "status": status,
                "venue": venue,
                "event_type_choices": EventType.choices,
                "status_choices": EventStatus.choices,
                "venue_choices": Venue.objects.order_by("name"),
                "can_manage_events": can_open,
                "cal_add_url": reverse("events:event_create") + "?" if can_open else "",
            }
        )

        return context


# -------------------------------------------------------------------
# Venues
# -------------------------------------------------------------------

class VenueListView(EventManageMixin, ListView):
    model = Venue
    template_name = "events/venue_list.html"
    context_object_name = "venues"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()

        q = (self.request.GET.get("q") or "").strip()
        venue_type = (self.request.GET.get("venue_type") or "").strip()
        is_active = (self.request.GET.get("is_active") or "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(city__icontains=q)
                | Q(district__icontains=q)
                | Q(phone__icontains=q)
            )

        if venue_type:
            qs = qs.filter(venue_type=venue_type)

        if is_active == "active":
            qs = qs.filter(is_active=True)
        elif is_active == "inactive":
            qs = qs.filter(is_active=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = (self.request.GET.get("q") or "").strip()
        context["venue_type"] = (self.request.GET.get("venue_type") or "").strip()
        context["is_active"] = (self.request.GET.get("is_active") or "").strip()
        context["venue_type_choices"] = VenueType.choices

        return context


class VenueDetailView(EventManageMixin, DetailView):
    model = Venue
    template_name = "events/venue_detail.html"
    context_object_name = "venue"


class VenueCreateView(EventManageMixin, CreateView):
    model = Venue
    form_class = VenueForm
    template_name = "events/venue_form.html"
    success_url = reverse_lazy("events:venue_list")

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Venue created successfully.")
        return super().form_valid(form)


class VenueUpdateView(EventManageMixin, UpdateView):
    model = Venue
    form_class = VenueForm
    template_name = "events/venue_form.html"
    success_url = reverse_lazy("events:venue_list")

    def form_valid(self, form):
        messages.success(self.request, "Venue updated successfully.")
        return super().form_valid(form)


class VenueDeleteView(EventCommonDeleteMixin):
    model = Venue
    success_url = reverse_lazy("events:venue_list")
    cancel_url_name = "events:venue_list"

    object_type = "venue"
    success_message = "Venue deleted successfully."
    warning_message = (
        "Deleting this venue will remove it from the venue list. "
        "Existing events linked to this venue will keep running, but the venue link may be cleared depending on model relationships."
    )

    def get_related_counts(self):
        return [
            ("Linked Events", self.object.events.count()),
        ]


# -------------------------------------------------------------------
# Events
# -------------------------------------------------------------------

class EventListView(EventManageMixin, ListView):
    model = Event
    template_name = "events/event_list.html"
    context_object_name = "events"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("project", "client", "primary_contact", "venue")
            .prefetch_related("services", "packages", "vendors", "inventory_items", "projects")
        )

        q = (self.request.GET.get("q") or "").strip()
        event_type = (self.request.GET.get("event_type") or "").strip()
        status = (self.request.GET.get("status") or "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(client__name__icontains=q)
                | Q(client__display_name__icontains=q)
                | Q(project__name__icontains=q)
                | Q(venue__name__icontains=q)
            )

        if event_type:
            qs = qs.filter(event_type=event_type)

        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["q"] = (self.request.GET.get("q") or "").strip()
        context["event_type"] = (self.request.GET.get("event_type") or "").strip()
        context["status"] = (self.request.GET.get("status") or "").strip()
        context["event_type_choices"] = EventType.choices
        context["status_choices"] = EventStatus.choices

        return context


class EventDetailView(EventCalendarAccessMixin, DetailView):
    """
    Everyone who works the event can open it from the calendar: managers
    get the edit actions, the crew a read-only page with the contract.
    """

    model = Event
    template_name = "events/event_detail.html"
    context_object_name = "event"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("project", "client", "primary_contact", "venue", "contract")
            .prefetch_related(
                "services",
                "packages",
                "vendors",
                "inventory_items",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        checklist = self.object.checklist

        context["linked_project"] = self.object.linked_project
        context["checklist"] = checklist
        context["checklist_items"] = (
            checklist.items
            .select_related("assigned_to")
            .order_by("is_done", "due_date", "title")
        )

        return context


class EventCreateView(EventManageMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"
    success_url = reverse_lazy("events:event_list")

    def get_initial(self):
        initial = super().get_initial()

        # Existing customers: Client page -> New Event.
        client_id = self.request.GET.get("client")
        if client_id and client_id.isdigit():
            client = Client.objects.filter(pk=client_id).first()
            if client:
                initial["client"] = client.pk
                initial["name"] = f"{client} - Wedding"

        # Calendar -> "+" on a day.
        raw_date = (self.request.GET.get("date") or "").strip()
        if raw_date:
            try:
                initial["date"] = date.fromisoformat(raw_date)
            except ValueError:
                pass

        return initial

    def form_valid(self, form):
        form.instance.owner = self.request.user

        self.object = form.save(commit=False)
        self.object.owner = self.request.user
        self.object.save()

        form.save_m2m()

        self.object.sync_auto_checklist(owner=self.request.user)

        messages.success(
            self.request,
            "Event created. Assign vendors and inventory, or create the project, from the event page.",
        )

        return redirect(self.object.get_absolute_url())


class EventUpdateView(EventManageMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"
    success_url = reverse_lazy("events:event_list")

    def form_valid(self, form):
        self.object = form.save()

        self.object.sync_auto_checklist(owner=self.request.user)

        messages.success(
            self.request,
            "Event updated successfully. Checklist was synced.",
        )

        return redirect(self.get_success_url())


class EventDeleteView(EventCommonDeleteMixin):
    model = Event
    success_url = reverse_lazy("events:event_list")
    cancel_url_name = "events:event_list"

    object_type = "event"
    success_message = "Event deleted successfully."
    warning_message = (
        "Deleting this event will also delete its checklist and checklist items. "
        "This does not delete clients, projects, services, packages, vendors, inventory, or venue records."
    )

    def get_related_counts(self):
        checklist = self.object.checklist

        return [
            ("Checklist Items", checklist.items.count()),
            ("Services", self.object.services.count()),
            ("Packages", self.object.packages.count()),
            ("Vendors", self.object.vendors.count()),
            ("Inventory Items", self.object.inventory_items.count()),
        ]

# -------------------------------------------------------------------
# Event Checklists
# -------------------------------------------------------------------

class EventChecklistListView(EventManageMixin, ListView):
    model = EventChecklist
    template_name = "events/checklist_list.html"
    context_object_name = "checklists"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("event", "event__client", "event__project")
            .prefetch_related("items")
        )

        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(event__name__icontains=q)
                | Q(event__client__name__icontains=q)
                | Q(event__project__name__icontains=q)
            )

        if status == "completed":
            qs = qs.exclude(items__is_done=False).distinct()
        elif status == "pending":
            qs = qs.filter(items__is_done=False).distinct()

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = (self.request.GET.get("q") or "").strip()
        context["status"] = (self.request.GET.get("status") or "").strip()
        return context


class EventChecklistDetailView(EventManageMixin, DetailView):
    model = EventChecklist
    template_name = "events/checklist_detail.html"
    context_object_name = "checklist"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("event", "event__client", "event__project")
            .prefetch_related("items")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["items"] = (
            self.object.items
            .select_related("assigned_to")
            .order_by("is_done", "due_date", "title")
        )
        return context


class EventChecklistCreateView(EventManageMixin, CreateView):
    model = EventChecklist
    form_class = EventChecklistForm
    template_name = "events/checklist_form.html"
    success_url = reverse_lazy("events:checklist_list")

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Checklist created successfully.")
        return super().form_valid(form)


class EventChecklistUpdateView(EventManageMixin, UpdateView):
    model = EventChecklist
    form_class = EventChecklistForm
    template_name = "events/checklist_form.html"
    success_url = reverse_lazy("events:checklist_list")

    def form_valid(self, form):
        messages.success(self.request, "Checklist updated successfully.")
        return super().form_valid(form)


class EventChecklistDeleteView(EventCommonDeleteMixin):
    model = EventChecklist
    success_url = reverse_lazy("events:checklist_list")
    cancel_url_name = "events:checklist_list"

    object_type = "checklist"
    success_message = "Checklist deleted successfully."
    warning_message = (
        "Deleting this checklist will also delete all checklist items inside it."
    )

    def get_related_counts(self):
        return [
            ("Event", self.object.event.name),
            ("Checklist Items", self.object.items.count()),
            ("Completed Items", self.object.done_items),
            ("Pending Items", self.object.pending_items),
        ]
    

# -------------------------------------------------------------------
# Checklist Items
# -------------------------------------------------------------------

class ChecklistItemCreateView(EventManageMixin, CreateView):
    model = ChecklistItem
    form_class = ChecklistItemForm
    template_name = "events/checklist_item_form.html"

    def get_initial(self):
        initial = super().get_initial()
        checklist_id = self.request.GET.get("checklist")

        if checklist_id:
            initial["checklist"] = checklist_id

        return initial

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Checklist item created successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("events:checklist_detail", args=[self.object.checklist_id])


class ChecklistItemUpdateView(EventManageMixin, UpdateView):
    model = ChecklistItem
    form_class = ChecklistItemForm
    template_name = "events/checklist_item_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Checklist item updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("events:checklist_detail", args=[self.object.checklist_id])


class ChecklistItemDeleteView(EventCommonDeleteMixin):
    model = ChecklistItem
    success_url = reverse_lazy("events:checklist_list")

    object_type = "checklist item"
    success_message = "Checklist item deleted successfully."
    warning_message = "This will delete only this checklist item."

    def get_success_url(self):
        return reverse("events:checklist_detail", args=[self.object.checklist_id])

    def get_cancel_url(self):
        return reverse("events:checklist_detail", args=[self.object.checklist_id])

    def get_related_counts(self):
        return [
            ("Checklist", self.object.checklist.title),
            ("Event", self.object.checklist.event.name),
            ("Done", "Yes" if self.object.is_done else "No"),
        ]
