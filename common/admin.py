from django.contrib import admin
from .models import (
    Choice,
    Communication,
    Document,
    ImportantNotice,
    LeaveRequest,
    UserLoginSession,
    UserNoticeAcknowledgement,
)


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ("type", "value", "is_active", "created_at")
    search_fields = ("type", "value")
    list_filter = ("type", "is_active")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "file", "created_at")
    list_display = ("title", "file", "related_client", "related_deal", "related_event", "created_at")
    search_fields = ("title", "description")
    list_filter = ("created_at",)


@admin.register(Communication)
class CommunicationAdmin(admin.ModelAdmin):
    list_display = (
        "channel",
        "subject",
        "client",
        "contact",
        "lead",
        "sent_by",
        "timestamp",
    )
    search_fields = ("subject", "message")
    list_filter = ("channel", "sent_by", "timestamp")


@admin.register(UserLoginSession)
class UserLoginSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "login_at",
        "logout_at",
        "end_reason",
        "checkout_review_status",
        "reviewed_by",
    )
    list_filter = ("end_reason", "checkout_review_status", "login_at")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    readonly_fields = ("session_key", "login_at", "last_activity_at")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "leave_type", "start_date", "end_date", "status", "reviewed_by")
    list_filter = ("leave_type", "status", "start_date")
    search_fields = ("user__username", "user__first_name", "user__last_name", "reason")


@admin.register(ImportantNotice)
class ImportantNoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "is_active", "requires_acknowledgement", "published_at")
    list_filter = ("is_active", "requires_acknowledgement", "published_at")
    search_fields = ("title", "body", "key")


@admin.register(UserNoticeAcknowledgement)
class UserNoticeAcknowledgementAdmin(admin.ModelAdmin):
    list_display = ("user", "notice", "agreed_at", "ip_address")
    list_filter = ("notice", "agreed_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "notice__title")
    readonly_fields = ("notice", "user", "agreed_at", "ip_address", "user_agent")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

