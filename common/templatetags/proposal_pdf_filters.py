# common/templatetags/proposal_pdf_filters.py
from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def inr(value):
    try:
        amount = int(Decimal(value or 0))
    except Exception:
        amount = 0

    s = str(amount)

    if len(s) <= 3:
        formatted = s
    else:
        last_three = s[-3:]
        rest = s[:-3]
        groups = []

        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]

        if rest:
            groups.insert(0, rest)

        formatted = ",".join(groups + [last_three])

    return f"₹ {formatted}/-"


@register.filter
def smart_item_title(item):
    if getattr(item, "service", None):
        return item.service.name

    if getattr(item, "package", None):
        return item.package.name

    if getattr(item, "description", None):
        return item.description

    return "Service Item"


@register.filter
def short_event_date(value):
    if not value:
        return ""

    return value.strftime("%b - %d").upper()


@register.filter
def clean_qty(value):
    try:
        value = Decimal(value)
    except Exception:
        return value

    if value == value.to_integral():
        return int(value)

    return value.normalize()