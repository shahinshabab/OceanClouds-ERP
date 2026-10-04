# events/models.py

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from common.models import TimeStamped, Owned
from crm.models import Client, Contact
from services.models import Vendor, Service, Package, InventoryItem


class EventType(models.TextChoices):
    WEDDING = "wedding", _("Wedding")
    RECEPTION = "reception", _("Reception")
    ENGAGEMENT = "engagement", _("Engagement")
    MEHNDI = "mehndi", _("Mehndi")
    SANGEET = "sangeet", _("Sangeet")
    HALDI = "haldi", _("Haldi")
    SAVE_THE_DATE = "save_the_date", _("Save the Date")
    BIRTHDAY = "birthday", _("Birthday")
    CORPORATE = "corporate", _("Corporate Event")
    OTHER = "other", _("Other")


class EventStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PLANNED = "planned", _("Planned")
    CONFIRMED = "confirmed", _("Confirmed")
    IN_PROGRESS = "in_progress", _("In Progress")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class VenueType(models.TextChoices):
    HOTEL = "hotel", _("Hotel")
    HALL = "hall", _("Function Hall")
    OUTDOOR = "outdoor", _("Outdoor")
    PRIVATE_PROPERTY = "private_property", _("Private Property")
    AUDITORIUM = "auditorium", _("Auditorium")
    RESORT = "resort", _("Resort")
    HOME = "home", _("Home")
    OTHER = "other", _("Other")


class ChecklistCategory(models.TextChoices):
    EVENT_SETUP = "event_setup", _("Event Setup")
    SERVICE = "service", _("Service")
    PACKAGE = "package", _("Package")
    VENDOR = "vendor", _("Vendor")
    INVENTORY = "inventory", _("Inventory")
    VENUE = "venue", _("Venue")
    COMMUNICATION = "communication", _("Communication")
    INTERNAL = "internal", _("Internal")
    OTHER = "other", _("Other")


class Venue(TimeStamped, Owned):
    name = models.CharField(max_length=255)

    venue_type = models.CharField(
        max_length=32,
        choices=VenueType.choices,
        default=VenueType.OTHER,
    )

    contact_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128, blank=True)
    district = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=128, blank=True, default="Kerala")
    country = models.CharField(max_length=128, blank=True, default="India")

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:venue_detail", args=[self.pk])


class Event(TimeStamped, Owned):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        related_name="linked_events",
        null=True,
        blank=True,
        help_text=_("Optional for now. Can be made required later."),
    )

    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
        help_text=_("Optional for now. Can be made required later."),
    )

    primary_contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )

    contract = models.ForeignKey(
        "sales.Contract",
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
        help_text=_("Signed contract this event was created from."),
    )

    name = models.CharField(max_length=255)

    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        default=EventType.WEDDING,
    )

    status = models.CharField(
        max_length=32,
        choices=EventStatus.choices,
        default=EventStatus.PLANNED,
    )

    date = models.DateField()
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)

    venue = models.ForeignKey(
        Venue,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )

    services = models.ManyToManyField(
        Service,
        related_name="events",
        blank=True,
    )

    packages = models.ManyToManyField(
        Package,
        related_name="events",
        blank=True,
    )

    vendors = models.ManyToManyField(
        Vendor,
        related_name="events",
        blank=True,
    )

    inventory_items = models.ManyToManyField(
        InventoryItem,
        related_name="events",
        blank=True,
    )

    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    vendor_template_sent = models.BooleanField(default=False)
    client_template_sent = models.BooleanField(default=False)

    vendor_template_sent_at = models.DateTimeField(null=True, blank=True)
    client_template_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("date", "start_time", "name")
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["event_type"]),
            models.Index(fields=["client"]),
            models.Index(fields=["project"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.date})"

    def get_absolute_url(self):
        return reverse("events:event_detail", args=[self.pk])

    @property
    def contact(self):
        """
        Contact person for this event, taken from the client.
        Falls back to a contact stored on older events.
        """
        if self.client_id:
            contact = self.client.primary_contact or self.client.contacts.first()
            if contact:
                return contact
        return self.primary_contact

    @property
    def linked_project(self):
        """
        Project for this event, whichever side holds the link.
        """
        if self.project_id:
            return self.project
        projects = list(self.projects.all())
        if not projects:
            return None
        return max(projects, key=lambda project: project.created_at)

    @property
    def checklist(self):
        checklist, created = EventChecklist.objects.get_or_create(
            event=self,
            defaults={
                "owner": self.owner,
                "title": f"Checklist for {self.name}",
            },
        )
        return checklist

    @property
    def checklist_total(self):
        return self.checklist.items.count()

    @property
    def checklist_done_count(self):
        return self.checklist.items.filter(is_done=True).count()

    @property
    def checklist_pending_count(self):
        return self.checklist.items.filter(is_done=False).count()

    def build_messaging_context(self):
        return {
            "event": self,
            "project": self.linked_project,
            "client": self.client,
            "primary_contact": self.contact,
            "venue": self.venue,
            "services": self.services.all(),
            "packages": self.packages.all(),
            "vendors": self.vendors.all(),
            "inventory_items": self.inventory_items.all(),
            "date": self.date,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }

    def sync_auto_checklist(self, owner=None):
        checklist, created = EventChecklist.objects.get_or_create(
            event=self,
            defaults={
                "owner": owner or self.owner,
                "title": f"Checklist for {self.name}",
            },
        )

        if owner and not checklist.owner_id:
            checklist.owner = owner
            checklist.save(update_fields=["owner"])

        def create_item(title, category, notes=""):
            exists = checklist.items.filter(
                title=title,
                category=category,
            ).exists()

            if not exists:
                ChecklistItem.objects.create(
                    checklist=checklist,
                    title=title,
                    category=category,
                    due_date=self.date,
                    owner=owner or self.owner,
                    notes=notes,
                )

        if self.venue:
            create_item(
                title=f"Confirm venue: {self.venue.name}",
                category=ChecklistCategory.VENUE,
                notes="Verify venue/location details before event.",
            )

        for service in self.services.all():
            create_item(
                title=f"Prepare service: {service.name}",
                category=ChecklistCategory.SERVICE,
                notes=f"Service code: {service.code or '-'}",
            )

        for package in self.packages.all():
            create_item(
                title=f"Prepare package: {package.name}",
                category=ChecklistCategory.PACKAGE,
                notes=f"Package code: {package.code or '-'}",
            )

        for vendor in self.vendors.all():
            create_item(
                title=f"Confirm vendor/operator: {vendor}",
                category=ChecklistCategory.VENDOR,
                notes="Send event details to vendor/operator.",
            )

        for item in self.inventory_items.all():
            create_item(
                title=f"Prepare inventory: {item.name}",
                category=ChecklistCategory.INVENTORY,
                notes=f"Available: {item.quantity_available}/{item.quantity_total} {item.unit}",
            )

        create_item(
            title="Send event plan to client",
            category=ChecklistCategory.COMMUNICATION,
            notes="Client template will be handled by messaging app.",
        )

        create_item(
            title="Send event plan to vendors",
            category=ChecklistCategory.COMMUNICATION,
            notes="Vendor template will be handled by messaging app.",
        )


class EventChecklist(TimeStamped, Owned):
    """
    One checklist per event.
    This groups all checklist items under a single event checklist.
    """

    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name="event_checklist",
    )

    title = models.CharField(max_length=255)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("event__date", "event__name")

    def __str__(self):
        return self.title or f"Checklist for {self.event}"

    def get_absolute_url(self):
        return reverse("events:checklist_detail", args=[self.pk])

    @property
    def total_items(self):
        return self.items.count()

    @property
    def done_items(self):
        return self.items.filter(is_done=True).count()

    @property
    def pending_items(self):
        return self.items.filter(is_done=False).count()


class ChecklistItem(TimeStamped, Owned):
    checklist = models.ForeignKey(
        EventChecklist,
        on_delete=models.CASCADE,
        related_name="items",
    )

    title = models.CharField(max_length=255)

    category = models.CharField(
        max_length=32,
        choices=ChecklistCategory.choices,
        default=ChecklistCategory.OTHER,
    )

    is_done = models.BooleanField(default=False)
    due_date = models.DateField(null=True, blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="event_checklist_items",
        null=True,
        blank=True,
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("checklist", "is_done", "due_date", "title")
        indexes = [
            models.Index(fields=["checklist", "is_done"]),
            models.Index(fields=["category"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["assigned_to"]),
        ]

    def __str__(self):
        return f"{self.title} - {self.checklist.event}"

    @property
    def event(self):
        return self.checklist.event