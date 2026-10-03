# crm/models.py
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, UniqueConstraint

from common.models import TimeStamped, Owned


class Client(TimeStamped, Owned):
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    billing_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True, default="Kerala")
    country = models.CharField(max_length=100, blank=True, default="India")

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.display_name or self.name

    @property
    def primary_contact(self):
        return self.contacts.filter(is_primary=True).first()


class Contact(TimeStamped, Owned):
    ROLE_CHOICES = [
        ("bride", "Bride"),
        ("groom", "Groom"),
        ("parent", "Parent"),
        ("sibling", "Sibling"),
        ("friend", "Friend"),
        ("other", "Other"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, blank=True)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)

    is_primary = models.BooleanField(default=False)
    allow_marketing = models.BooleanField(default=True)

    class Meta:
        ordering = ["client__name", "first_name"]
        constraints = [
            UniqueConstraint(
                fields=["client", "email"],
                condition=~Q(email=""),
                name="uniq_contact_email_per_client_non_empty",
            )
        ]

    def __str__(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return f"{full_name} ({self.client})"


class Inquiry(TimeStamped, Owned):
    CHANNEL_CHOICES = [
        ("website", "Website Form"),
        ("phone", "Phone Call"),
        ("whatsapp", "WhatsApp"),
        ("instagram", "Instagram DM"),
        ("facebook", "Facebook"),
        ("email", "Email"),
        ("referral", "Referral"),
        ("other", "Other"),
    ]

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_CLOSED = "closed"
    STATUS_CONVERTED_TO_LEAD = "converted_to_lead"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_CONVERTED_TO_LEAD, "Converted to Lead"),
    ]

    channel = models.CharField(max_length=50, choices=CHANNEL_CHOICES, default="instagram")
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_OPEN)

    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)

    wedding_date = models.DateField(null=True, blank=True)
    wedding_city = models.CharField(max_length=100, blank=True)
    wedding_district = models.CharField(max_length=100, blank=True)
    wedding_state = models.CharField(max_length=100, blank=True, default="Kerala")
    wedding_country = models.CharField(max_length=100, blank=True, default="India")

    message = models.TextField(blank=True)

    lead = models.ForeignKey(
        "Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_inquiries",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inquiries",
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_inquiries",
    )

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if not self.name and not self.email and not self.phone and not self.whatsapp:
            raise ValidationError("At least one of name, email, phone, or WhatsApp is required.")

    def __str__(self):
        contact = self.name or self.email or self.phone or self.whatsapp or "Inquiry"
        return f"{contact} - {self.get_status_display()}"


class Lead(TimeStamped, Owned):
    STATUS_NEW = "new"
    STATUS_CONTACTED = "contacted"
    STATUS_QUALIFIED = "qualified"
    STATUS_PROPOSAL_SENT = "proposal_sent"
    STATUS_PROPOSAL_ACCEPTED = "proposal_accepted"
    STATUS_LOST = "lost"
    STATUS_CONVERTED_TO_DEAL = "converted_to_deal"
    STATUS_CONVERTED_TO_CLIENT = "converted_to_client"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_QUALIFIED, "Qualified"),
        (STATUS_PROPOSAL_SENT, "Proposal Sent"),
        (STATUS_PROPOSAL_ACCEPTED, "Proposal Accepted"),
        (STATUS_LOST, "Lost"),
        (STATUS_CONVERTED_TO_DEAL, "Converted to Deal"),
        (STATUS_CONVERTED_TO_CLIENT, "Converted to Client"),
    ]

    SOURCE_CHOICES = Inquiry.CHANNEL_CHOICES

    inquiry = models.ForeignKey(
        Inquiry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )

    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)

    wedding_date = models.DateField(null=True, blank=True)
    wedding_city = models.CharField(max_length=100, blank=True)
    wedding_district = models.CharField(max_length=100, blank=True)
    wedding_state = models.CharField(max_length=100, blank=True, default="Kerala")
    wedding_country = models.CharField(max_length=100, blank=True, default="India")

    budget_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_NEW)
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, blank=True)
    source_detail = models.CharField(max_length=255, blank=True)

    notes = models.TextField(blank=True)
    next_action_date = models.DateField(null=True, blank=True)
    next_action_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class Review(TimeStamped, Owned):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    next_action = models.CharField(max_length=255, blank=True)
    next_action_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        base = self.title or self.comment[:30] or "Review"
        return f"{base} - {self.client}"

    @property
    def has_rating(self):
        return self.rating is not None
