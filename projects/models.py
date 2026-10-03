# projects/models.py

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from common.models import TimeStamped, Owned


def _format_seconds_hm(seconds):
    seconds = int(seconds or 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


# ============================================================
# Choice enums
# ============================================================

class ProjectStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ACTIVE = "active", "Active"
    ON_HOLD = "on_hold", "On Hold"
    COMPLETED = "completed", "Completed"
    CLOSED = "closed", "Closed / Payment Collected"
    CANCELLED = "cancelled", "Cancelled"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class ProductionDepartment(models.TextChoices):
    PHOTO = "photo", "Photo"
    VIDEO = "video", "Video"
    DESIGN = "design", "Design"
    ALBUM = "album", "Album"
    MIXED = "mixed", "Mixed"
    OTHER = "other", "Other"


class TaskCategory(models.TextChoices):
    IMPORT = "import", "Import"
    SELECTION = "selection", "Selection / Culling"
    EDITING = "editing", "Editing"
    COLOR = "color", "Color / Grading"
    AUDIO = "audio", "Audio / Sync"
    DESIGN = "design", "Design"
    EXPORT = "export", "Export"
    QC = "qc", "Quality Check"
    DELIVERY_SUPPORT = "delivery_support", "Delivery Support"
    OTHER = "other", "Other"


class DeliverableCategory(models.TextChoices):
    ALBUM = "album", "Album"
    POSTER = "poster", "Poster"
    SAVE_THE_DATE = "save_the_date", "Save the Date"
    PROMO_VIDEO = "promo_video", "Promo Video"
    REEL = "reel", "Video Reel"
    HIGHLIGHT_FILM = "highlight_film", "Highlight Film"
    FULL_FILM = "full_film", "Full Wedding Film"
    PHOTO_SET = "photo_set", "Edited Photo Set"
    OTHER = "other", "Other"


class TaskStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In Progress"
    PAUSED = "paused", "Paused"
    REVIEW = "review", "Review"
    REVISION = "revision", "Revision"
    COMPLETED = "completed", "Completed"
    BLOCKED = "blocked", "Blocked"
    CANCELLED = "cancelled", "Cancelled"


class DeliverableStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    WAITING_FOR_TASKS = "waiting_for_tasks", "Waiting for Tasks"
    IN_PROGRESS = "in_progress", "In Progress"
    PAUSED = "paused", "Paused"
    INTERNAL_REVIEW = "internal_review", "Internal Review"
    CLIENT_REVIEW = "client_review", "Client Review"
    REVISION_REQUESTED = "revision_requested", "Revision Requested"
    READY_TO_DELIVER = "ready_to_deliver", "Ready to Deliver"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


class DeliverableType(models.TextChoices):
    DIGITAL = "digital", "Digital"
    PHYSICAL = "physical", "Physical"
    MIXED = "mixed", "Digital + Physical"


class WorkTargetType(models.TextChoices):
    TASK = "task", "Task"
    DELIVERABLE = "deliverable", "Deliverable"


class WorkSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ENDED = "ended", "Ended"



# ============================================================
# Project
# ============================================================

class Project(TimeStamped, Owned):
    """
    One wedding/event production project.

    Client/deal are optional so old projects can be created first
    and linked later.
    """

    name = models.CharField(max_length=255)

    client = models.ForeignKey(
        "crm.Client",
        on_delete=models.SET_NULL,
        related_name="projects",
        null=True,
        blank=True,
        help_text="Optional at first. Can be linked later.",
    )

    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.SET_NULL,
        related_name="projects",
        null=True,
        blank=True,
        help_text="Optional linked deal. Can be linked later.",
    )

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        related_name="projects",
        null=True,
        blank=True,
        help_text="Optional linked wedding/event.",
    )
    project_directory = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Main folder or drive path for this project.",
    )
    description = models.TextField(blank=True)

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="managed_projects",
        null=True,
        blank=True,
        help_text="Project Manager responsible for this project.",
    )

    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=30,
        choices=ProjectStatus.choices,
        default=ProjectStatus.PLANNED,
        db_index=True,
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )

    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["completed_at"]),
            models.Index(fields=["manager", "status"]),
        ]

    def __str__(self):
        if self.client:
            return f"{self.name} ({self.client})"
        return self.name

    def get_absolute_url(self):
        return reverse("projects:project_detail", args=[self.pk])

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        if self.status in [
            ProjectStatus.COMPLETED,
            ProjectStatus.CLOSED,
            ProjectStatus.CANCELLED,
        ]:
            return False
        return timezone.localdate() > self.due_date

    @property
    def tasks_completed(self):
        """
        True if there are tasks and all non-cancelled tasks are completed.
        """
        qs = self.tasks.exclude(status=TaskStatus.CANCELLED)
        if not qs.exists():
            return False
        return not qs.exclude(status=TaskStatus.COMPLETED).exists()

    @property
    def deliverables_delivered(self):
        """
        True if there are deliverables and all non-cancelled deliverables are delivered.
        """
        qs = self.deliverables.exclude(status=DeliverableStatus.CANCELLED)
        if not qs.exists():
            return False
        return not qs.exclude(status=DeliverableStatus.DELIVERED).exists()

    @property
    def can_be_completed(self):
        return self.tasks_completed and self.deliverables_delivered

    @property
    def progress_percent(self):
        """
        Report-friendly progress:
        - 50% based on task completion
        - 50% based on deliverable delivery
        """
        task_qs = self.tasks.exclude(status=TaskStatus.CANCELLED)
        deliverable_qs = self.deliverables.exclude(status=DeliverableStatus.CANCELLED)

        task_total = task_qs.count()
        deliverable_total = deliverable_qs.count()

        task_score = 0
        deliverable_score = 0

        if task_total:
            completed = task_qs.filter(status=TaskStatus.COMPLETED).count()
            task_score = (completed / task_total) * 50

        if deliverable_total:
            delivered = deliverable_qs.filter(status=DeliverableStatus.DELIVERED).count()
            deliverable_score = (delivered / deliverable_total) * 50

        return int(task_score + deliverable_score)

    @property
    def progress_bar_width(self):
        return max(int(self.progress_percent or 0), 5)

    @property
    def total_work_seconds(self):
        return sum(
            max(int(session.live_work_seconds or 0), 0)
            for session in self.work_sessions.all()
        )

    @property
    def total_work_hours(self):
        return round(self.total_work_seconds / 3600, 2)

    @property
    def total_work_hm(self):
        return _format_seconds_hm(self.total_work_seconds)

    @property
    def has_client_review(self):
        """
        True only when this project has a linked client
        and that client has at least one review.
        """
        if not self.client_id:
            return False
        return self.client.reviews.exists()

    @property
    def can_be_closed(self):
        """
        Closing rule:
        - Project should be completed first.
        - If client is linked, at least one client review is required.
        - If client is not linked yet, allow closing for now because client is nullable.
        """
        if self.status != ProjectStatus.COMPLETED:
            return False

        if self.client_id and not self.has_client_review:
            return False

        return True

    def mark_closed(self):
        """
        Close project only after review is collected when client exists.
        """
        if self.status == ProjectStatus.CLOSED:
            return

        if self.status != ProjectStatus.COMPLETED:
            raise ValidationError(
                "Cannot close project before it is marked as completed."
            )

        if self.client_id and not self.has_client_review:
            raise ValidationError(
                "Cannot close project until a client review is collected."
            )

        self.status = ProjectStatus.CLOSED
        self.save(update_fields=["status"])

    def mark_completed(self):
        if self.status == ProjectStatus.COMPLETED:
            return

        if not self.can_be_completed:
            raise ValidationError(
                "Cannot complete project until all tasks are completed and all deliverables are delivered."
            )

        now = timezone.now()
        self.status = ProjectStatus.COMPLETED
        self.completed_at = now
        self.save(update_fields=["status", "completed_at"])

    def clean(self):
        super().clean()

        if self.status == ProjectStatus.CLOSED:
            if self.pk:
                old_project = Project.objects.filter(pk=self.pk).only("status").first()
                old_status = old_project.status if old_project else None
            else:
                old_status = None

            if old_status != ProjectStatus.COMPLETED:
                raise ValidationError({
                    "status": "Project must be completed before it can be closed."
                })

            if self.client_id and not self.has_client_review:
                raise ValidationError({
                    "status": "Client review must be collected before closing this project."
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
# ============================================================
# Task
# ============================================================

class Task(TimeStamped, Owned):
    """
    Internal production work:
    import photos, colour photos, grade videos, design, export, QC, etc.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
    )

    name = models.CharField(max_length=255)

    department = models.CharField(
        max_length=30,
        choices=ProductionDepartment.choices,
        default=ProductionDepartment.OTHER,
        db_index=True,
    )

    category = models.CharField(
        max_length=40,
        choices=TaskCategory.choices,
        default=TaskCategory.OTHER,
        db_index=True,
    )

    directory = models.CharField(max_length=255, blank=True, default="")
    count = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="project_tasks",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        db_index=True,
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )

    start_date = models.DateField(null=True, blank=True, db_index=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)

    estimated_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Optional estimated time in minutes.",
    )


    first_started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["start_date", "due_date", "status", "priority", "created_at"]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["department", "category"]),
            models.Index(fields=["start_date"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["completed_at"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.project}"

    def get_absolute_url(self):
        return reverse("projects:task_detail", args=[self.pk])

    @property
    def is_completed(self):
        return self.status == TaskStatus.COMPLETED

    @property
    def is_active_working(self):
        return self.status == TaskStatus.IN_PROGRESS

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        if self.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
            return False
        return timezone.localdate() > self.due_date

    @property
    def total_work_seconds(self):
        return sum(
            max(int(session.live_work_seconds or 0), 0)
            for session in self.work_sessions.all()
        )

    @property
    def total_work_hours(self):
        return round(self.total_work_seconds / 3600, 2)

    @property
    def total_work_hm(self):
        return _format_seconds_hm(self.total_work_seconds)

    def mark_completed(self):
        now = timezone.now()
        self.status = TaskStatus.COMPLETED
        if not self.completed_at:
            self.completed_at = now
        self.save(update_fields=["status", "completed_at"])


# ============================================================
# Deliverable
# ============================================================

class Deliverable(TimeStamped, Owned):
    """
    Client-facing final output:
    album, poster, save-the-date, reel, promo, final film, etc.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="deliverables",
    )

    name = models.CharField(max_length=255)

    category = models.CharField(
        max_length=40,
        choices=DeliverableCategory.choices,
        default=DeliverableCategory.OTHER,
        db_index=True,
    )

    type = models.CharField(
        max_length=20,
        choices=DeliverableType.choices,
        default=DeliverableType.DIGITAL,
        db_index=True,
    )

    department = models.CharField(
        max_length=30,
        choices=ProductionDepartment.choices,
        default=ProductionDepartment.OTHER,
        db_index=True,
    )

    directory = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_deliverables",
    )

    status = models.CharField(
        max_length=40,
        choices=DeliverableStatus.choices,
        default=DeliverableStatus.PENDING,
        db_index=True,
    )

    tasks = models.ManyToManyField(
        Task,
        related_name="deliverables",
        blank=True,
        help_text="Tasks required before this deliverable can start/deliver.",
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )

    file_link = models.URLField(blank=True)
    file = models.FileField(upload_to="deliverables/", blank=True, null=True)

    preview_link = models.URLField(blank=True)
    version = models.PositiveIntegerField(default=1)
    revision_count = models.PositiveIntegerField(default=0)

    delivery_medium = models.CharField(
        max_length=100,
        blank=True,
        help_text="Google Drive, WhatsApp, Pendrive, Printed Album, etc.",
    )
    quantity = models.PositiveIntegerField(null=True, blank=True)
    handed_over_to = models.CharField(max_length=255, blank=True)

    start_date = models.DateField(null=True, blank=True, db_index=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)

    first_started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ready_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["start_date", "due_date", "status", "created_at"]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["department", "category"]),
            models.Index(fields=["type", "status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["start_date"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["delivered_at"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.project}"

    def get_absolute_url(self):
        return reverse("projects:deliverable_detail", args=[self.pk])

    @property
    def is_delivered(self):
        return self.status == DeliverableStatus.DELIVERED

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        if self.status in [DeliverableStatus.DELIVERED, DeliverableStatus.CANCELLED]:
            return False
        return timezone.localdate() > self.due_date

    @property
    def linked_task_count(self):
        return self.tasks.count()

    @property
    def completed_task_count(self):
        return self.tasks.filter(status=TaskStatus.COMPLETED).count()

    @property
    def task_progress_percent(self):
        total = self.linked_task_count
        if total == 0:
            return 0
        return int((self.completed_task_count / total) * 100)

    @property
    def required_tasks_completed(self):
        """
        Deliverable can move to IN_PROGRESS only when linked tasks are completed.
        If no tasks are linked, allow manual progress.
        """
        qs = self.tasks.all()
        if not qs.exists():
            return True
        return not qs.exclude(status=TaskStatus.COMPLETED).exists()

    @property
    def total_work_seconds(self):
        return sum(
            max(int(session.live_work_seconds or 0), 0)
            for session in self.work_sessions.all()
        )

    @property
    def total_work_hours(self):
        return round(self.total_work_seconds / 3600, 2)

    @property
    def total_work_hm(self):
        return _format_seconds_hm(self.total_work_seconds)

    def can_move_to_in_progress(self):
        return self.required_tasks_completed

    def can_be_marked_delivered(self):
        return self.required_tasks_completed

    def mark_delivered(self):
        if not self.can_be_marked_delivered():
            raise ValidationError(
                "All linked tasks must be completed before this deliverable can be delivered."
            )

        now = timezone.now()
        self.status = DeliverableStatus.DELIVERED
        if not self.delivered_at:
            self.delivered_at = now
        self.save(update_fields=["status", "delivered_at"])



# ============================================================
# Work session tracking
# ============================================================

class WorkSession(TimeStamped, Owned):
    """
    Actual work timer for a task or deliverable.

    Rules:
    - One employee can have only one ACTIVE work session at a time.
    - PAUSED sessions do not count future time.
    - work_seconds stores counted time.
    - Admin/project manager can view all; restriction is only for who can start work.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_work_sessions",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="work_sessions",
    )

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="work_sessions",
    )

    deliverable = models.ForeignKey(
        Deliverable,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="work_sessions",
    )

    status = models.CharField(
        max_length=20,
        choices=WorkSessionStatus.choices,
        default=WorkSessionStatus.ACTIVE,
        db_index=True,
    )

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_resumed_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)

    work_seconds = models.PositiveIntegerField(default=0)

    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["project", "status"]),
            models.Index(fields=["task", "status"]),
            models.Index(fields=["deliverable", "status"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["ended_at"]),
        ]
        constraints = [
           models.CheckConstraint(
                condition=(
                    (Q(task__isnull=False) & Q(deliverable__isnull=True)) |
                    (Q(task__isnull=True) & Q(deliverable__isnull=False))
                ),
                name="worksession_single_target",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status=WorkSessionStatus.ACTIVE),
                name="one_active_worksession_per_user",
            ),
        ]

    def __str__(self):
        target = self.task or self.deliverable
        return f"{self.user} - {target} - {self.status}"

    @property
    def target(self):
        return self.task or self.deliverable

    @property
    def live_work_seconds(self):
        """
        Returns stored work_seconds + currently active running time.
        Paused time is not counted.
        """
        total = self.work_seconds
        if self.status == WorkSessionStatus.ACTIVE and self.last_resumed_at:
            total += int((timezone.now() - self.last_resumed_at).total_seconds())
        return total

    @property
    def live_work_hours(self):
        return round(self.live_work_seconds / 3600, 2)

    @property
    def live_work_hm(self):
        return _format_seconds_hm(self.live_work_seconds)

    def clean(self):
        super().clean()

        if (self.task is None) == (self.deliverable is None):
            raise ValidationError("WorkSession must have exactly one target: task or deliverable.")

        target_project_id = None
        if self.task_id:
            target_project_id = self.task.project_id
        if self.deliverable_id:
            target_project_id = self.deliverable.project_id

        if self.project_id and target_project_id and self.project_id != target_project_id:
            raise ValidationError("WorkSession.project must match the target project.")

    def save(self, *args, **kwargs):
        if self.status == WorkSessionStatus.ACTIVE and not self.last_resumed_at:
            self.last_resumed_at = self.started_at or timezone.now()
        self.full_clean()
        return super().save(*args, **kwargs)

    def _add_active_duration(self, stopped_at=None):
        if self.status == WorkSessionStatus.ACTIVE and self.last_resumed_at:
            stopped_at = stopped_at or timezone.now()
            delta = stopped_at - self.last_resumed_at
            self.work_seconds += max(int(delta.total_seconds()), 0)

    def pause(self, paused_at=None):
        if self.status != WorkSessionStatus.ACTIVE:
            return

        paused_at = paused_at or timezone.now()
        if self.last_resumed_at and paused_at < self.last_resumed_at:
            paused_at = self.last_resumed_at

        self._add_active_duration(stopped_at=paused_at)
        self.status = WorkSessionStatus.PAUSED
        self.paused_at = paused_at
        self.last_resumed_at = None
        self.save(update_fields=["work_seconds", "status", "paused_at", "last_resumed_at"])

    def resume(self):
        if self.status != WorkSessionStatus.PAUSED:
            return

        now = timezone.now()
        self.status = WorkSessionStatus.ACTIVE
        self.last_resumed_at = now
        self.paused_at = None
        self.save(update_fields=["status", "last_resumed_at", "paused_at"])

    def end(self):
        if self.status == WorkSessionStatus.ENDED:
            return

        now = timezone.now()
        self._add_active_duration()
        self.status = WorkSessionStatus.ENDED
        self.ended_at = now
        self.save(update_fields=["work_seconds", "status", "ended_at"])
