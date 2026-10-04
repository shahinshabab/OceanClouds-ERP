# ui/templatetags/ui_tags.py
from django import template

register = template.Library()

STATUS_TONES = {
    "status-solid": {
        "won", "accepted", "signed", "paid", "completed", "confirmed", "delivered",
        "approved", "done", "converted_to_lead", "converted_to_deal", "converted_to_client",
        "proposal_accepted", "resolved", "sent_ok", "success",
    },
    "status-outline": {
        "in_progress", "sent", "pending_signature", "issued", "partially_paid",
        "proposal_sent", "negotiation", "advance_received", "contract_sent",
        "qualified", "contacted", "planned", "active", "review", "in_review", "running",
        "scheduled", "open",
    },
    "status-warning": {"overdue", "on_hold", "expired", "pending", "paused", "high", "urgent"},
    "status-danger": {"lost", "cancelled", "canceled", "rejected", "failed", "critical"},
    "status-muted": {"draft", "new", "closed", "inactive", "low", "archived"},
}

_LOOKUP = {value: tone for tone, values in STATUS_TONES.items() for value in values}


@register.filter
def status_tone(value):
    """CSS class for a status pill: {{ obj.status|status_tone }}."""
    return _LOOKUP.get(str(value or "").strip().lower(), "")


@register.inclusion_tag("ui/partials/status.html")
def status_pill(value, label=None):
    """<span class="status ...">Label</span> for a choice value."""
    return {"tone": status_tone(value), "label": label or str(value or "").replace("_", " ").title()}


@register.filter
def initials(user_or_name):
    name = ""
    if hasattr(user_or_name, "get_full_name"):
        name = user_or_name.get_full_name() or user_or_name.get_username()
    else:
        name = str(user_or_name or "")
    parts = [p for p in name.replace("&", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@register.filter
def inr(value, decimals=0):
    """Indian digit grouping: 1234567.5 -> ₹12,34,568 (or with decimals)."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    if value in (None, ""):
        return "—"
    try:
        number = Decimal(str(value))
        places = int(decimals)
    except (InvalidOperation, ValueError, TypeError):
        return value
    quant = Decimal(1).scaleb(-places) if places else Decimal(1)
    number = number.quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    whole, _, frac = f"{abs(number):f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}" + (f".{frac}" if places else "")


FULL_WIDTH_WIDGETS = ("Textarea", "CheckboxSelectMultiple", "SelectMultiple", "ClearableFileInput", "FileInput")


@register.inclusion_tag("ui/partials/field.html")
def field(bound, col="auto", label=None, hint=None, prefix=None, suffix=None, placeholder=None):
    """
    One form field in the shared layout: label, widget, hint and errors.

        {% field form.name "col-md-6" %}
        {% field form.amount "col-md-4" prefix="₹" %}

    col="auto" makes text areas and multi-selects full width, the rest half.
    """
    if bound is None or bound == "":
        return {"bound": None}
    widget = bound.field.widget
    kind = type(widget).__name__
    if col == "auto":
        col = "col-12" if kind in FULL_WIDTH_WIDGETS else "col-md-6"

    attrs = {}
    css = widget.attrs.get("class", "")
    if bound.errors:
        css = f"{css} is-invalid".strip()
    if css:
        attrs["class"] = css
    if placeholder:
        attrs["placeholder"] = placeholder

    return {
        "bound": bound,
        "col": col,
        "label": label if label is not None else bound.label,
        "hint": hint if hint is not None else bound.help_text,
        "prefix": prefix,
        "suffix": suffix,
        "widget": bound.as_widget(attrs=attrs),
        "is_check": kind == "CheckboxInput",
        "is_multi_check": kind == "CheckboxSelectMultiple",
        "required": bound.field.required,
    }


@register.inclusion_tag("ui/partials/form_auto.html")
def form_fields(form, col="auto", exclude=""):
    """Every visible field of a form in the shared layout, minus `exclude` (comma list)."""
    skip = {name.strip() for name in exclude.split(",") if name.strip()}
    return {"fields": [f for f in form.visible_fields() if f.name not in skip], "col": col}
