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


def _indian_grouping(amount):
    s = str(amount)
    if len(s) <= 3:
        return s
    last_three = s[-3:]
    rest = s[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join(groups + [last_three])


@register.filter
def money(value):
    """
    ₹1,89,980 (Indian grouping, no paise unless present).
    """
    try:
        amount = Decimal(value or 0)
    except Exception:
        amount = Decimal("0")

    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    whole = int(amount)
    paise = int((amount - whole) * 100)
    text = _indian_grouping(whole)
    if paise:
        text += f".{paise:02d}"
    return f"{sign}₹{text}"


@register.filter
def item_title(item):
    """
    The line's own description first (it can be edited per proposal),
    then the catalogue name.
    """
    for value in (
        getattr(item, "description", ""),
        getattr(getattr(item, "service", None), "name", ""),
        getattr(getattr(item, "package", None), "name", ""),
    ):
        if value:
            return value
    return "Service"


@register.filter
def item_subtitle(item):
    service = getattr(item, "service", None)
    if service is not None and getattr(service, "summary", ""):
        return service.summary
    package = getattr(item, "package", None)
    if package is not None and getattr(package, "tagline", ""):
        return package.tagline
    return ""


@register.filter
def included(deliverables):
    return [d for d in deliverables.all() if getattr(d, "is_included", True)]


@register.filter
def lines(text):
    return [line.strip(" -•\t") for line in str(text or "").splitlines() if line.strip(" -•\t")]


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

@register.filter
def halves(values):
    """
    Split a list into two columns, the left one taking the extra item.
    """
    values = list(values or [])
    middle = (len(values) + 1) // 2
    return [
        {"items": values[:middle], "offset": 0},
        {"items": values[middle:], "offset": middle},
    ]
