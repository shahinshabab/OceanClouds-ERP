from django.utils import timezone


def _get_month_info():
    today = timezone.now().date()
    this_year = today.year
    this_month = today.month

    if this_month == 1:
        prev_year = this_year - 1
        prev_month = 12
    else:
        prev_year = this_year
        prev_month = this_month - 1

    return this_year, this_month, prev_year, prev_month


def _pct_change(current: int, previous: int) -> int:
    if previous == 0:
        return 100 if current > 0 else 0

    return round((current - previous) * 100 / previous)


def _trend_data(current: int, previous: int):
    pct = _pct_change(current, previous)

    if pct > 0:
        return {
            "pct": pct,
            "abs_pct": abs(pct),
            "class": "text-success",
            "icon": "bi-arrow-up-right",
            "label": "Higher than last month",
        }

    if pct < 0:
        return {
            "pct": pct,
            "abs_pct": abs(pct),
            "class": "text-danger",
            "icon": "bi-arrow-down-right",
            "label": "Lower than last month",
        }

    return {
        "pct": pct,
        "abs_pct": 0,
        "class": "text-muted",
        "icon": "bi-dash-lg",
        "label": "Same as last month",
    }


def _monthly_card(title, current, previous, icon, bg_class="bg-light"):
    trend = _trend_data(current, previous)

    return {
        "title": title,
        "value": current,
        "previous": previous,
        "icon": icon,
        "bg_class": bg_class,
        "trend": trend,
    }


def _simple_card(title, value, subtitle, icon, bg_class="bg-light"):
    return {
        "title": title,
        "value": value,
        "subtitle": subtitle,
        "icon": icon,
        "bg_class": bg_class,
    }
