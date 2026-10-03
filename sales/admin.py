# sales/admin.py

from django.contrib import admin

from .models import (
    Deal,
    Proposal,
    ProposalPlan,
    ProposalEventDay,
    ProposalItem,
    ProposalItemDeliverable,
    Contract,
    ContractEventDay,
    ContractItem,
    ContractDeliverable,
    Invoice,
    InvoiceItem,
    Payment,
)


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "client",
        "lead",
        "stage",
        "amount",
        "expected_close_date",
        "is_active",
        "closed_on",
        "owner",
        "created_at",
    )

    list_filter = (
        "stage",
        "is_active",
        "expected_close_date",
        "closed_on",
        "created_at",
    )

    search_fields = (
        "name",
        "description",
        "client__name",
        "client__display_name",
        "lead__name",
        "lead__email",
        "lead__phone",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "owner",
        "client",
        "lead",
    )

    fieldsets = (
        ("Deal Details", {
            "fields": (
                "owner",
                "name",
                "client",
                "lead",
                "stage",
                "amount",
                "expected_close_date",
                "description",
                "is_active",
                "closed_on",
            )
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "deal",
        "version",
        "status",
        "valid_until",
        "accepted_plan",
        "subtotal",
        "discount",
        "tax_rate",
        "tax_amount",
        "total",
        "owner",
        "created_at",
    )

    list_filter = (
        "status",
        "valid_until",
        "created_at",
    )

    search_fields = (
        "title",
        "notes",
        "deal__name",
        "deal__client__name",
        "deal__client__display_name",
        "accepted_plan__name",
    )

    readonly_fields = (
        "subtotal",
        "discount",
        "tax_rate",
        "tax_amount",
        "total",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "owner",
        "deal",
        "accepted_plan",
    )

    fieldsets = (
        ("Proposal Details", {
            "fields": (
                "owner",
                "deal",
                "title",
                "version",
                "status",
                "valid_until",
                "accepted_plan",
            )
        }),
        ("Totals", {
            "fields": (
                "subtotal",
                "discount",
                "tax_rate",
                "tax_amount",
                "total",
            )
        }),
        ("Notes", {
            "fields": (
                "notes",
            )
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(ProposalPlan)
class ProposalPlanAdmin(admin.ModelAdmin):
    list_display = (
        "proposal",
        "name",
        "is_primary",
        "is_accepted",
        "subtotal",
        "discount",
        "tax_rate",
        "tax_amount",
        "total",
        "sort_order",
        "owner",
        "created_at",
    )

    list_filter = (
        "is_primary",
        "is_accepted",
        "created_at",
    )

    search_fields = (
        "proposal__title",
        "proposal__deal__name",
        "name",
        "description",
    )

    readonly_fields = (
        "subtotal",
        "tax_amount",
        "total",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "owner",
        "proposal",
    )

    fieldsets = (
        ("Plan Details", {
            "fields": (
                "owner",
                "proposal",
                "name",
                "description",
                "is_primary",
                "is_accepted",
                "sort_order",
            )
        }),
        ("Totals", {
            "fields": (
                "subtotal",
                "discount",
                "tax_rate",
                "tax_amount",
                "total",
            )
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(ProposalEventDay)
class ProposalEventDayAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "event_date",
        "title",
        "venue",
        "start_time",
        "end_time",
        "sort_order",
    )

    list_filter = (
        "event_date",
    )

    search_fields = (
        "plan__name",
        "plan__proposal__title",
        "title",
        "venue",
        "notes",
    )

    autocomplete_fields = (
        "plan",
    )

    fieldsets = (
        ("Event Day", {
            "fields": (
                "plan",
                "event_date",
                "title",
                "venue",
                "start_time",
                "end_time",
                "notes",
                "sort_order",
            )
        }),
    )


@admin.register(ProposalItem)
class ProposalItemAdmin(admin.ModelAdmin):
    list_display = (
        "event_day",
        "service",
        "package",
        "description",
        "quantity",
        "unit_price",
        "line_total",
        "sort_order",
    )

    list_filter = (
        "service",
        "package",
    )

    search_fields = (
        "event_day__title",
        "event_day__plan__name",
        "event_day__plan__proposal__title",
        "service__name",
        "service__code",
        "package__name",
        "package__code",
        "description",
        "notes",
    )

    readonly_fields = (
        "line_total",
    )

    autocomplete_fields = (
        "event_day",
        "service",
        "package",
    )

    fieldsets = (
        ("Proposal Item", {
            "fields": (
                "event_day",
                "service",
                "package",
                "description",
                "quantity",
                "unit_price",
                "line_total",
                "notes",
                "sort_order",
            )
        }),
    )


@admin.register(ProposalItemDeliverable)
class ProposalItemDeliverableAdmin(admin.ModelAdmin):
    list_display = (
        "proposal_item",
        "title",
        "quantity",
        "unit",
        "sort_order",
        "is_included",
    )

    list_filter = (
        "unit",
        "is_included",
    )

    search_fields = (
        "proposal_item__description",
        "proposal_item__event_day__title",
        "title",
        "description",
    )

    autocomplete_fields = (
        "proposal_item",
    )

    fieldsets = (
        ("Proposal Deliverable", {
            "fields": (
                "proposal_item",
                "title",
                "description",
                "quantity",
                "unit",
                "sort_order",
                "is_included",
            )
        }),
    )


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "deal",
        "proposal",
        "proposal_plan",
        "status",
        "signed_date",
        "start_date",
        "end_date",
        "subtotal",
        "discount",
        "tax_rate",
        "tax_amount",
        "total",
        "owner",
        "created_at",
    )

    list_filter = (
        "status",
        "signed_date",
        "start_date",
        "end_date",
        "created_at",
    )

    search_fields = (
        "number",
        "terms",
        "deal__name",
        "deal__client__name",
        "deal__client__display_name",
        "proposal__title",
        "proposal_plan__name",
    )

    readonly_fields = (
        "number",
        "signing_token",
        "signed_at",
        "signed_by_name",
        "signed_ip_address",
        "signed_user_agent",
        "subtotal",
        "tax_amount",
        "total",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "owner",
        "deal",
        "proposal",
        "proposal_plan",
    )

    fieldsets = (
        ("Contract Details", {
            "fields": (
                "owner",
                "deal",
                "proposal",
                "proposal_plan",
                "number",
                "status",
                "signed_date",
                "start_date",
                "end_date",
                "file",
            )
        }),
        ("Signing Details", {
            "fields": (
                "signing_token",
                "signed_at",
                "signed_by_name",
                "signed_ip_address",
                "signed_user_agent",
            ),
            "classes": ("collapse",),
        }),
        ("Totals", {
            "fields": (
                "subtotal",
                "discount",
                "tax_rate",
                "tax_amount",
                "total",
            )
        }),
        ("Terms", {
            "fields": (
                "terms",
            )
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(ContractEventDay)
class ContractEventDayAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "proposal_event_day",
        "event_date",
        "title",
        "venue",
        "start_time",
        "end_time",
        "sort_order",
    )

    list_filter = (
        "event_date",
    )

    search_fields = (
        "contract__number",
        "contract__deal__name",
        "proposal_event_day__title",
        "title",
        "venue",
        "notes",
    )

    autocomplete_fields = (
        "contract",
        "proposal_event_day",
    )

    fieldsets = (
        ("Contract Event Day", {
            "fields": (
                "contract",
                "proposal_event_day",
                "event_date",
                "title",
                "venue",
                "start_time",
                "end_time",
                "notes",
                "sort_order",
            )
        }),
    )


@admin.register(ContractItem)
class ContractItemAdmin(admin.ModelAdmin):
    list_display = (
        "contract_event_day",
        "proposal_item",
        "service",
        "package",
        "description",
        "quantity",
        "unit_price",
        "line_total",
        "sort_order",
    )

    list_filter = (
        "service",
        "package",
    )

    search_fields = (
        "contract_event_day__contract__number",
        "contract_event_day__contract__deal__name",
        "contract_event_day__title",
        "proposal_item__description",
        "service__name",
        "package__name",
        "description",
        "notes",
    )

    readonly_fields = (
        "line_total",
    )

    autocomplete_fields = (
        "contract_event_day",
        "proposal_item",
        "service",
        "package",
    )

    fieldsets = (
        ("Contract Item", {
            "fields": (
                "contract_event_day",
                "proposal_item",
                "service",
                "package",
                "description",
                "quantity",
                "unit_price",
                "line_total",
                "notes",
                "sort_order",
            )
        }),
    )


@admin.register(ContractDeliverable)
class ContractDeliverableAdmin(admin.ModelAdmin):
    list_display = (
        "contract_item",
        "proposal_deliverable",
        "title",
        "quantity",
        "unit",
        "sort_order",
        "is_included",
    )

    list_filter = (
        "unit",
        "is_included",
    )

    search_fields = (
        "contract_item__description",
        "contract_item__contract_event_day__contract__number",
        "proposal_deliverable__title",
        "title",
        "description",
    )

    autocomplete_fields = (
        "contract_item",
        "proposal_deliverable",
    )

    fieldsets = (
        ("Contract Deliverable", {
            "fields": (
                "contract_item",
                "proposal_deliverable",
                "title",
                "description",
                "quantity",
                "unit",
                "sort_order",
                "is_included",
            )
        }),
    )


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "deal",
        "contract",
        "issue_date",
        "due_date",
        "status",
        "subtotal",
        "discount",
        "tax_rate",
        "tax",
        "total",
        "amount_paid",
        "balance",
        "owner",
        "created_at",
    )

    list_filter = (
        "status",
        "issue_date",
        "due_date",
        "created_at",
    )

    search_fields = (
        "number",
        "notes",
        "deal__name",
        "deal__client__name",
        "deal__client__display_name",
        "contract__number",
    )

    readonly_fields = (
        "number",
        "subtotal",
        "discount",
        "tax_rate",
        "tax",
        "total",
        "amount_paid",
        "balance",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "owner",
        "deal",
        "contract",
    )

    fieldsets = (
        ("Invoice Details", {
            "fields": (
                "owner",
                "deal",
                "contract",
                "number",
                "issue_date",
                "due_date",
                "status",
            )
        }),
        ("Totals", {
            "fields": (
                "subtotal",
                "discount",
                "tax_rate",
                "tax",
                "total",
                "amount_paid",
                "balance",
            )
        }),
        ("Notes", {
            "fields": (
                "notes",
            )
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "contract_item",
        "description",
        "quantity",
        "unit_price",
        "tax_rate",
        "line_subtotal",
        "tax_amount",
        "line_total",
    )

    search_fields = (
        "invoice__number",
        "invoice__deal__name",
        "contract_item__description",
        "description",
    )

    readonly_fields = (
        "line_subtotal",
        "tax_amount",
        "line_total",
    )

    autocomplete_fields = (
        "invoice",
        "contract_item",
    )

    fieldsets = (
        ("Invoice Item", {
            "fields": (
                "invoice",
                "contract_item",
                "description",
                "quantity",
                "unit_price",
                "tax_rate",
                "line_subtotal",
                "tax_amount",
                "line_total",
            )
        }),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "date",
        "amount",
        "payment_type",
        "method",
        "reference",
        "received_by",
        "owner",
        "created_at",
    )

    list_filter = (
        "payment_type",
        "method",
        "date",
        "received_by",
        "created_at",
    )

    search_fields = (
        "invoice__number",
        "invoice__deal__name",
        "invoice__deal__client__name",
        "reference",
        "notes",
        "received_by__username",
        "received_by__first_name",
        "received_by__last_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "owner",
        "invoice",
        "received_by",
    )

    fieldsets = (
        ("Payment Details", {
            "fields": (
                "owner",
                "invoice",
                "date",
                "amount",
                "payment_type",
                "method",
                "reference",
                "received_by",
            )
        }),
        ("Notes", {
            "fields": (
                "notes",
            )
        }),
        ("System Info", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )
