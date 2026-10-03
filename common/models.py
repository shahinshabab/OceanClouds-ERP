# common/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

# ----------------------------------------------------------------------
# ABSTRACT MODELS
# ----------------------------------------------------------------------


class TimeStamped(models.Model):
    """
    Adds created_at / updated_at timestamps to each model.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDelete(models.Model):
    """
    Adds soft delete: instead of deleting objects,
    mark them as inactive via is_deleted.
    """

    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """
        Soft-delete: mark as deleted instead of removing the row.
        """
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])


class Owned(models.Model):
    """
    Tracks which user created/owns the object.
    Useful for multi-user CRM (Admin, CRM Manager, Project Manager, Employee).
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_owned",
        help_text="User who created or owns this record.",
    )

    class Meta:
        abstract = True


# ----------------------------------------------------------------------
# GENERIC CHOICE TABLE
# ----------------------------------------------------------------------


class Choice(TimeStamped):
    """
    Generic choice table for dropdowns:
    - Lead source
    - Vendor type
    - Service category
    - Task priority
    - etc.

    Example:
        Choice(type="lead_source", value="Instagram")
    """

    type = models.CharField(
        max_length=50,
        help_text="Machine key for the group of choices, e.g. 'lead_source', 'vendor_type'.",
        db_index=True,
    )
    value = models.CharField(
        max_length=255,
        help_text="Human-readable value shown in dropdown, e.g. 'Instagram'.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ["type", "value"]
        ordering = ["type", "value"]
        verbose_name = "Choice"
        verbose_name_plural = "Choices"

    def __str__(self):
        return f"{self.type}: {self.value}"


# ----------------------------------------------------------------------
# DOCUMENT STORAGE
# ----------------------------------------------------------------------


class Document(TimeStamped, Owned):
    """
    Universal document model used across CRM:
    - Proposal PDFs
    - Invoices
    - Contracts
    - Event checklists
    - Client-uploaded files
    """

    file = models.FileField(
        upload_to="documents/%Y/%m/%d/",
        help_text="Uploaded file (PDF, image, etc.).",
    )
    title = models.CharField(
        max_length=255,
        help_text="Short title for this document.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description or notes about this document.",
    )

    related_client = models.ForeignKey(
        "crm.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Client this document is primarily related to.",
    )

    related_deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Deal/booking this document is related to.",
    )

    related_event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Event this document is related to.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Document"
        verbose_name_plural = "Documents"

    def __str__(self):
        return self.title


# ----------------------------------------------------------------------
# COMMUNICATION LOGS
# ----------------------------------------------------------------------


class Communication(TimeStamped, Owned):
    """
    Logs communication:
    - Email
    - SMS
    - WhatsApp
    - Call summary
    """

    CHANNEL_CHOICES = [
        ("email", "Email"),
        ("sms", "SMS"),
        ("whatsapp", "WhatsApp"),
        ("call", "Phone Call"),
    ]

    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        help_text="Medium used for this communication.",
    )
    subject = models.CharField(
        max_length=255,
        blank=True,
        help_text="Subject or short summary of the communication.",
    )
    message = models.TextField(
        blank=True,
        help_text="Full message body or call summary.",
    )

    client = models.ForeignKey(
        "crm.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
        help_text="Client this communication is associated with.",
    )

    contact = models.ForeignKey(
        "crm.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
        help_text="Specific contact person (bride, groom, etc.) involved.",
    )

    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
        help_text="Lead this communication is tied to, if any.",
    )

    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_communications",
        help_text="User who sent or logged this communication.",
    )

    timestamp = models.DateTimeField(
        default=timezone.now,
        help_text="When this communication was sent or took place.",
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Communication"
        verbose_name_plural = "Communications"

    def __str__(self):
        return f"{self.get_channel_display()} - {self.subject or 'No subject'}"


# ----------------------------------------------------------------------
# NOTIFICATIONS
# ----------------------------------------------------------------------


class Notification(models.Model):
    class Type(models.TextChoices):
        # CRM
        INQUIRY_ASSIGNED = "inquiry_assigned", "Inquiry assigned"
        LEAD_FOLLOW_UP = "lead_follow_up", "Lead follow-up"

        # Sales
        DEAL_EXPECTED_CLOSE = "deal_expected_close", "Deal expected close"
        PROPOSAL_DUE = "proposal_due", "Proposal due"
        CONTRACT_ENDING = "contract_ending", "Contract ending"
        INVOICE_DUE = "invoice_due", "Invoice due"

        # Projects
        PROJECT_ASSIGNED = "project_assigned", "Project assigned"
        PROJECT_DUE = "project_due", "Project due"
        PROJECT_COMPLETED_REVIEW_PENDING = (
            "project_completed_review_pending",
            "Project completed - review pending",
        )

        TASK_ASSIGNED = "task_assigned", "Task assigned"
        TASK_DUE = "task_due", "Task due"

        DELIVERABLE_ASSIGNED = "deliverable_assigned", "Deliverable assigned"
        DELIVERABLE_DUE = "deliverable_due", "Deliverable due"

        # Future
        EVENT_REMINDER = "event_reminder", "Event reminder"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_sent",
    )

    notif_type = models.CharField(
        max_length=64,
        choices=Type.choices,
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    message = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)

    # Important for duplicate prevention
    dedupe_key = models.CharField(
        max_length=180,
        blank=True,
        null=True,
        db_index=True,
        help_text="Prevents the same notification being created repeatedly.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["notif_type", "created_at"]),
            models.Index(fields=["dedupe_key"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"],
                condition=(
                    models.Q(dedupe_key__isnull=False)
                    & ~models.Q(dedupe_key="")
                ),
                name="unique_notification_per_recipient_dedupe_key",
            )
        ]
    def __str__(self):
        return self.message or self.get_notif_type_display()

    def get_target_url(self):
        if self.target and hasattr(self.target, "get_absolute_url"):
            return self.target.get_absolute_url()
        return "#"




# common/models.py
class UserSessionEndReason(models.TextChoices):
    LOGOUT = "logout", "Manual Logout"
    AUTO_TIMEOUT = "auto_timeout", "Auto Timeout"
    SESSION_EXPIRED = "session_expired", "Fixed Session Expired"
    SESSION_REPLACED = "session_replaced", "Replaced by New Login"
    SYSTEM = "system", "System"
    UNKNOWN = "unknown", "Unknown"


class CheckoutReviewStatus(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not Required"
    PENDING = "pending", "Missing Checkout"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class UserLoginSession(models.Model):
    """
    Tracks website login/logout duration for every user.

    This belongs in common app because it is global,
    not project-specific.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_sessions",
    )

    session_key = models.CharField(max_length=100, db_index=True)

    login_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    logout_at = models.DateTimeField(null=True, blank=True, db_index=True)

    end_reason = models.CharField(
        max_length=30,
        choices=UserSessionEndReason.choices,
        blank=True,
        default="",
        db_index=True,
    )

    checkout_review_status = models.CharField(
        max_length=20,
        choices=CheckoutReviewStatus.choices,
        default=CheckoutReviewStatus.NOT_REQUIRED,
        db_index=True,
    )
    requested_logout_at = models.DateTimeField(null=True, blank=True)
    checkout_request_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_checkout_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ["-login_at"]
        indexes = [
            models.Index(fields=["user", "login_at"]),
            models.Index(fields=["user", "logout_at"]),
            models.Index(fields=["session_key"]),
            models.Index(fields=["logout_at", "end_reason"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(logout_at__isnull=True),
                name="one_active_login_session_per_user",
            ),
        ]
        permissions = [
            ("review_attendance", "Can review missing attendance checkouts"),
        ]

    def __str__(self):
        return f"{self.user} login {self.login_at} - {self.logout_at or 'ACTIVE'}"

    @property
    def is_active(self):
        return self.logout_at is None

    @property
    def duration_seconds(self):
        end = self.logout_at or timezone.now()
        return int((end - self.login_at).total_seconds())

    @property
    def duration_hours(self):
        return round(self.duration_seconds / 3600, 2)

    def close(self, reason=UserSessionEndReason.LOGOUT):
        if self.logout_at:
            return

        self.logout_at = timezone.now()
        self.end_reason = reason
        self.save(update_fields=["logout_at", "end_reason"])

    @property
    def approved_logout_at(self):
        if self.checkout_review_status == CheckoutReviewStatus.APPROVED:
            return self.requested_logout_at
        if self.checkout_review_status == CheckoutReviewStatus.NOT_REQUIRED:
            return self.logout_at
        return None


class LeaveType(models.TextChoices):
    ANNUAL = "annual", "Annual Leave"
    SICK = "sick", "Sick Leave"
    CASUAL = "casual", "Casual Leave"
    UNPAID = "unpaid", "Unpaid Leave"
    OTHER = "other", "Other"


class LeaveStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class LeaveRequest(TimeStamped):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    leave_type = models.CharField(max_length=20, choices=LeaveType.choices)
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=LeaveStatus.choices,
        default=LeaveStatus.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_leave_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="leave_end_not_before_start",
            ),
        ]
        permissions = [
            ("review_leave_requests", "Can review employee leave requests"),
        ]

    @property
    def day_count(self):
        return (self.end_date - self.start_date).days + 1

    def __str__(self):
        return f"{self.user} - {self.start_date} to {self.end_date}"


class ImportantNotice(TimeStamped):
    key = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=255)
    body = models.TextField()
    is_active = models.BooleanField(default=True, db_index=True)
    requires_acknowledgement = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["published_at", "pk"]

    def __str__(self):
        return self.title


class UserNoticeAcknowledgement(models.Model):
    notice = models.ForeignKey(
        ImportantNotice,
        on_delete=models.CASCADE,
        related_name="acknowledgements",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notice_acknowledgements",
    )
    agreed_at = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ["-agreed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["notice", "user"],
                name="one_notice_agreement_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} agreed to {self.notice}"
