# projects/admin.py

from django.contrib import admin

from .models import Project, Task, Deliverable, WorkSession


class TaskInline(admin.TabularInline):
    model = Task
    extra = 0
    fields = (
        "name",
        "department",
        "category",
        "assigned_to",
        "status",
        "priority",
        "due_date",
        "sort_order",
    )
    autocomplete_fields = ("assigned_to",)


class DeliverableInline(admin.TabularInline):
    model = Deliverable
    extra = 0
    fields = (
        "name",
        "category",
        "type",
        "department",
        "assigned_to",
        "status",
        "priority_display",
        "due_date",
    )
    readonly_fields = ("priority_display",)
    autocomplete_fields = ("assigned_to",)

    def priority_display(self, obj):
        return obj.project.priority if obj and obj.project_id else "-"
    priority_display.short_description = "Project Priority"


class WorkSessionInline(admin.TabularInline):
    model = WorkSession
    extra = 0
    fields = (
        "user",
        "task",
        "deliverable",
        "status",
        "started_at",
        "ended_at",
        "work_seconds",
    )
    readonly_fields = (
        "started_at",
        "ended_at",
        "work_seconds",
    )
    autocomplete_fields = (
        "user",
        "task",
        "deliverable",
    )


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "client",
        "deal",
        "manager",
        "status",
        "priority",
        "start_date",
        "due_date",
        "is_overdue",
        "progress_percent",
        "total_work_hm",
        "owner",
        "created_at",
    )
    list_filter = (
        "status",
        "priority",
        "manager",
        "start_date",
        "due_date",
        "completed_at",
        "created_at",
    )
    search_fields = (
        "name",
        "description",
        "project_directory",
        "client__name",
        "client__display_name",
        "deal__name",
        "events__name",
        "manager__username",
        "manager__first_name",
        "manager__last_name",
    )
    readonly_fields = (
        "is_overdue",
        "tasks_completed",
        "deliverables_delivered",
        "can_be_completed",
        "progress_percent",
        "progress_bar_width",
        "total_work_seconds",
        "total_work_hm",
        "completed_at",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "owner",
        "client",
        "deal",
        "manager",
    )
    inlines = (
        TaskInline,
        DeliverableInline,
        WorkSessionInline,
    )
    fieldsets = (
        ("Project Details", {
            "fields": (
                "owner",
                "name",
                "client",
                "deal",
                "project_directory",
                "description",
                "manager",
            )
        }),
        ("Timeline / Status", {
            "fields": (
                "start_date",
                "due_date",
                "status",
                "priority",
                "completed_at",
            )
        }),
        ("Calculated Progress", {
            "fields": (
                "is_overdue",
                "tasks_completed",
                "deliverables_delivered",
                "can_be_completed",
                "progress_percent",
                "progress_bar_width",
                "total_work_seconds",
                "total_work_hm",
            ),
            "classes": ("collapse",),
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "project",
        "department",
        "category",
        "assigned_to",
        "status",
        "priority",
        "due_date",
        "is_overdue",
        "total_work_hm",
        "owner",
        "created_at",
    )
    list_filter = (
        "department",
        "category",
        "status",
        "priority",
        "assigned_to",
        "due_date",
        "completed_at",
        "created_at",
    )
    search_fields = (
        "name",
        "description",
        "directory",
        "count",
        "project__name",
        "project__client__name",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
    )
    readonly_fields = (
        "is_completed",
        "is_active_working",
        "is_overdue",
        "total_work_seconds",
        "total_work_hm",
        "first_started_at",
        "completed_at",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "owner",
        "project",
        "assigned_to",
    )
    fieldsets = (
        ("Task Details", {
            "fields": (
                "owner",
                "project",
                "name",
                "department",
                "category",
                "directory",
                "count",
                "description",
                "assigned_to",
            )
        }),
        ("Status / Time", {
            "fields": (
                "status",
                "priority",
                "due_date",
                "estimated_minutes",
                "first_started_at",
                "completed_at",
            )
        }),
        ("Calculated", {
            "fields": (
                "is_completed",
                "is_active_working",
                "is_overdue",
                "total_work_seconds",
                "total_work_hm",
            ),
            "classes": ("collapse",),
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(Deliverable)
class DeliverableAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "project",
        "category",
        "type",
        "department",
        "assigned_to",
        "status",
        "due_date",
        "is_overdue",
        "task_progress_percent",
        "total_work_hm",
        "owner",
        "created_at",
    )
    list_filter = (
        "category",
        "type",
        "department",
        "status",
        "assigned_to",
        "due_date",
        "ready_at",
        "delivered_at",
        "created_at",
    )
    search_fields = (
        "name",
        "description",
        "directory",
        "delivery_medium",
        "handed_over_to",
        "project__name",
        "project__client__name",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
    )
    readonly_fields = (
        "is_delivered",
        "is_overdue",
        "linked_task_count",
        "completed_task_count",
        "task_progress_percent",
        "required_tasks_completed",
        "total_work_seconds",
        "total_work_hm",
        "first_started_at",
        "ready_at",
        "delivered_at",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "owner",
        "project",
        "assigned_to",
        "tasks",
    )
    filter_horizontal = ("tasks",)
    fieldsets = (
        ("Deliverable Details", {
            "fields": (
                "owner",
                "project",
                "name",
                "category",
                "type",
                "department",
                "directory",
                "description",
                "assigned_to",
                "tasks",
            )
        }),
        ("File / Delivery", {
            "fields": (
                "file_link",
                "file",
                "preview_link",
                "version",
                "revision_count",
                "delivery_medium",
                "quantity",
                "handed_over_to",
            )
        }),
        ("Status / Dates", {
            "fields": (
                "status",
                "due_date",
                "first_started_at",
                "ready_at",
                "delivered_at",
            )
        }),
        ("Calculated", {
            "fields": (
                "is_delivered",
                "is_overdue",
                "linked_task_count",
                "completed_task_count",
                "task_progress_percent",
                "required_tasks_completed",
                "total_work_seconds",
                "total_work_hm",
            ),
            "classes": ("collapse",),
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "project",
        "target",
        "status",
        "started_at",
        "last_resumed_at",
        "paused_at",
        "ended_at",
        "work_seconds",
        "live_work_hm",
        "owner",
        "created_at",
    )
    list_filter = (
        "status",
        "user",
        "project",
        "started_at",
        "ended_at",
        "created_at",
    )
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "project__name",
        "task__name",
        "deliverable__name",
        "note",
    )
    readonly_fields = (
        "target",
        "live_work_seconds",
        "live_work_hm",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "owner",
        "user",
        "project",
        "task",
        "deliverable",
    )
    fieldsets = (
        ("Work Session", {
            "fields": (
                "owner",
                "user",
                "project",
                "task",
                "deliverable",
                "target",
                "status",
            )
        }),
        ("Time", {
            "fields": (
                "started_at",
                "last_resumed_at",
                "paused_at",
                "ended_at",
                "work_seconds",
                "live_work_seconds",
                "live_work_hm",
            )
        }),
        ("Notes", {
            "fields": ("note",)
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )