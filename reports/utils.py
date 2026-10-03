import json
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from common.models import CheckoutReviewStatus, UserSessionEndReason
from common.roles import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER, user_has_role
from projects.models import Deliverable, Task, WorkSession


User = get_user_model()
ATTENDANCE_REQUIRED_SECONDS = 8 * 60 * 60


def _money(value):
    return value or Decimal("0.00")


def _int(value):
    return value or 0


def _get_date_range(request):
    """
    Common date filter.

    Default:
    current month start to today.
    """
    today = timezone.localdate()

    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")

    if not date_from:
        date_from = today.replace(day=1)

    if not date_to:
        date_to = today

    return date_from, date_to


def _selected_user_id(request):
    value = (request.GET.get("user") or "").strip()
    if value.isdigit():
        return int(value)
    return None


def _users_in_role(role_name):
    return (
        User.objects
        .filter(is_active=True, groups__name=role_name)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


def _all_employee_users():
    return (
        User.objects
        .filter(
            is_active=True,
            groups__name__in=[
                ROLE_EMPLOYEE,
                ROLE_PROJECT_MANAGER,
            ],
        )
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


def _employee_options_for_user(user):
    """
    Admin:
    all employees and project managers.

    Project Manager:
    employees who have work sessions under projects managed by this manager,
    plus the manager themselves.

    Employee:
    only themselves.
    """
    if user_has_role(user, ROLE_ADMIN):
        return _all_employee_users()

    if user_has_role(user, ROLE_PROJECT_MANAGER):
        work_session_ids = (
            WorkSession.objects
            .filter(project__manager=user)
            .values_list("user_id", flat=True)
        )
        task_employee_ids = Task.objects.filter(
            project__manager=user,
            assigned_to__isnull=False,
        ).values_list("assigned_to_id", flat=True)
        deliverable_employee_ids = Deliverable.objects.filter(
            project__manager=user,
            assigned_to__isnull=False,
        ).values_list("assigned_to_id", flat=True)
        employee_ids = set(work_session_ids) | set(task_employee_ids) | set(deliverable_employee_ids)

        return (
            User.objects
            .filter(
                Q(id__in=employee_ids) | Q(id=user.id),
                is_active=True,
            )
            .distinct()
            .order_by("first_name", "last_name", "username")
        )

    return User.objects.filter(id=user.id, is_active=True)


def _user_display(user):
    if not user:
        return "All users"

    full_name = user.get_full_name()
    return full_name or user.username


def _base_date_filter(qs, field_name, date_from, date_to):
    """
    For DateTimeField.
    Example:
    created_at, started_at, login_at.
    """
    return qs.filter(
        **{
            f"{field_name}__date__gte": date_from,
            f"{field_name}__date__lte": date_to,
        }
    )


def _base_plain_date_filter(qs, field_name, date_from, date_to):
    """
    For DateField.
    """
    return qs.filter(
        **{
            f"{field_name}__gte": date_from,
            f"{field_name}__lte": date_to,
        }
    )


def _replace_query_params(request, **new_params):
    """
    Keep existing filters, replace/add params, and remove empty values.
    """
    params = request.GET.copy()

    for key, value in new_params.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = value

    return f"{request.path}?{params.urlencode()}"


def _get_current_sunday_week_start():
    """
    Sunday-based current week.

    Python weekday:
    Monday = 0
    Sunday = 6

    If today is Wednesday 06 May 2026:
    weekday = 2
    days_since_sunday = 3
    week_start = Sunday 03 May 2026
    week_end = Saturday 09 May 2026
    """
    today = timezone.localdate()
    days_since_sunday = (today.weekday() + 1) % 7
    return today - timedelta(days=days_since_sunday)


def _get_login_week(request):
    """
    Query param:
    ?login_week=2026-05-03

    Default:
    current Sunday-to-Saturday week.
    """
    week_start = parse_date(request.GET.get("login_week") or "")

    if not week_start:
        week_start = _get_current_sunday_week_start()

    # Force Sunday even if another date is passed.
    days_since_sunday = (week_start.weekday() + 1) % 7
    week_start = week_start - timedelta(days=days_since_sunday)

    week_end = week_start + timedelta(days=6)

    return week_start, week_end


def _format_seconds_to_hours(seconds):
    seconds = seconds or 0
    return round(seconds / 3600, 2)


def _format_seconds_hm(seconds):
    seconds = int(seconds or 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def _sum_work_session_seconds(work_sessions):
    """Include stored time and the live portion of active work sessions."""
    return sum(
        max(int(session.live_work_seconds or 0), 0)
        for session in work_sessions
    )


def _legacy_auto_logout_idle_seconds():
    """Historical three-hour idle window used by pre-upgrade records only."""
    return int(getattr(settings, "LEGACY_AUTO_LOGOUT_IDLE_SECONDS", 3 * 60 * 60) or 0)


def _effective_attendance_logout(session):
    if session.end_reason in [
        UserSessionEndReason.SESSION_EXPIRED,
        UserSessionEndReason.SESSION_REPLACED,
    ]:
        if session.checkout_review_status == CheckoutReviewStatus.APPROVED:
            return session.requested_logout_at
        return None
    return session.logout_at


def _login_session_seconds(session, local_login, local_logout):
    effective_logout = _effective_attendance_logout(session)
    if effective_logout is None:
        return 0, 0
    local_logout = timezone.localtime(effective_logout)
    total_seconds = max(int((local_logout - local_login).total_seconds()), 0)

    if session.end_reason != UserSessionEndReason.AUTO_TIMEOUT:
        return total_seconds, 0

    idle_seconds = min(total_seconds, _legacy_auto_logout_idle_seconds())
    return max(total_seconds - idle_seconds, 0), idle_seconds


def _build_attendance_summary(login_sessions_qs, date_from, date_to):
    """
    Count attendance from completed, user-valid login sessions.

    Manual logout, auto-timeout, and replaced sessions all contain valid used
    time. The auto-timeout idle window is excluded, and sessions crossing
    midnight are split across their actual local calendar days.
    """
    completed_sessions = (
        login_sessions_qs
        .filter(
            login_at__date__lte=date_to,
            logout_at__date__gte=date_from,
            logout_at__isnull=False,
            end_reason__in=[
                UserSessionEndReason.LOGOUT,
                UserSessionEndReason.AUTO_TIMEOUT,
                UserSessionEndReason.SESSION_EXPIRED,
                UserSessionEndReason.SESSION_REPLACED,
            ],
        )
        .select_related("user")
        .order_by("login_at")
    )

    seconds_by_user_date = defaultdict(int)
    current_tz = timezone.get_current_timezone()
    range_start = timezone.make_aware(
        datetime.combine(date_from, time.min),
        current_tz,
    )
    range_end = timezone.make_aware(
        datetime.combine(date_to + timedelta(days=1), time.min),
        current_tz,
    )

    for session in completed_sessions:
        local_login = timezone.localtime(session.login_at)
        effective_logout = _effective_attendance_logout(session)
        if effective_logout is None:
            continue
        local_logout = timezone.localtime(effective_logout)

        if session.end_reason == UserSessionEndReason.AUTO_TIMEOUT:
            local_logout = max(
                local_login,
                local_logout - timedelta(seconds=_legacy_auto_logout_idle_seconds()),
            )

        segment_start = max(local_login, range_start)
        segment_end = min(local_logout, range_end)

        while segment_start < segment_end:
            next_day = timezone.make_aware(
                datetime.combine(
                    segment_start.date() + timedelta(days=1),
                    time.min,
                ),
                current_tz,
            )
            day_end = min(segment_end, next_day)
            attendance_key = (session.user_id, segment_start.date())
            seconds_by_user_date[attendance_key] += max(
                int((day_end - segment_start).total_seconds()),
                0,
            )
            segment_start = day_end

    attended_days = [
        {
            "user_id": user_id,
            "date": attendance_date,
            "seconds": seconds,
            "hours": _format_seconds_to_hours(seconds),
            "hm": _format_seconds_hm(seconds),
        }
        for (user_id, attendance_date), seconds in seconds_by_user_date.items()
        if seconds >= ATTENDANCE_REQUIRED_SECONDS
    ]

    attended_days.sort(key=lambda row: (row["date"], row["user_id"]))

    return {
        "required_seconds": ATTENDANCE_REQUIRED_SECONDS,
        "required_hm": _format_seconds_hm(ATTENDANCE_REQUIRED_SECONDS),
        "attendance_days": len(attended_days),
        "days": attended_days,
    }


def _build_login_week_chart(request, login_sessions_qs):
    """
    Sunday to Saturday login duration chart.

    Green:
    manual logout

    Red:
    auto timeout
    """
    week_start, week_end = _get_login_week(request)

    sessions = (
        login_sessions_qs
        .filter(
            login_at__date__gte=week_start,
            login_at__date__lte=week_end,
            logout_at__isnull=False,
            end_reason__in=[
                UserSessionEndReason.LOGOUT,
                UserSessionEndReason.AUTO_TIMEOUT,
                UserSessionEndReason.SESSION_EXPIRED,
                UserSessionEndReason.SESSION_REPLACED,
            ],
        )
        .select_related("user")
        .order_by("login_at")
    )

    day_map = {}

    for i in range(7):
        day = week_start + timedelta(days=i)
        day_map[day] = {
            "date": day,
            "label": day.strftime("%a"),
            "manual_seconds": 0,
            "auto_seconds": 0,
            "idle_seconds": 0,
        }

    for session in sessions:
        local_login = timezone.localtime(session.login_at)
        effective_logout = _effective_attendance_logout(session)
        if effective_logout is None:
            continue
        local_logout = timezone.localtime(effective_logout)

        session_date = local_login.date()

        if session_date not in day_map:
            continue

        used_seconds, idle_seconds = _login_session_seconds(
            session,
            local_login,
            local_logout,
        )

        day_map[session_date]["manual_seconds"] += used_seconds
        day_map[session_date]["auto_seconds"] += 0
        day_map[session_date]["idle_seconds"] = (
            day_map[session_date].get("idle_seconds", 0) + idle_seconds
        )

    chart_days = []

    for row in day_map.values():
        manual_hours = _format_seconds_to_hours(row["manual_seconds"])
        auto_hours = _format_seconds_to_hours(row["auto_seconds"])
        total_hours = round(manual_hours + auto_hours, 2)

        chart_days.append({
            "date": row["date"],
            "label": row["label"],
            "manual_hours": manual_hours,
            "auto_hours": auto_hours,
            "total_hours": total_hours,
            "manual_hm": _format_seconds_hm(row["manual_seconds"]),
            "auto_hm": _format_seconds_hm(row["auto_seconds"]),
            "idle_hm": _format_seconds_hm(row.get("idle_seconds", 0)),
        })

    chart_labels = [row["label"] for row in chart_days]
    manual_hours = [row["manual_hours"] for row in chart_days]
    auto_hours = [row["auto_hours"] for row in chart_days]
    manual_hm = [row["manual_hm"] for row in chart_days]
    auto_hm = [row["auto_hm"] for row in chart_days]

    return {
        "week_start": week_start,
        "week_end": week_end,
        "previous_week_url": _replace_query_params(
            request,
            login_week=(week_start - timedelta(days=7)).isoformat(),
            download=None,
        ),
        "next_week_url": _replace_query_params(
            request,
            login_week=(week_start + timedelta(days=7)).isoformat(),
            download=None,
        ),
        "chart_days": chart_days,
        "chart_labels_json": json.dumps(chart_labels),
        "manual_hours_json": json.dumps(manual_hours),
        "auto_hours_json": json.dumps(auto_hours),
        "manual_hm_json": json.dumps(manual_hm),
        "auto_hm_json": json.dumps(auto_hm),
        "manual_total_hours": round(sum(manual_hours), 2),
        "auto_total_hours": round(sum(auto_hours), 2),
        "grand_total_hours": round(sum(manual_hours) + sum(auto_hours), 2),
        "grand_total_hm": _format_seconds_hm(
            sum(row["manual_seconds"] + row["auto_seconds"] for row in day_map.values())
        ),
        "legacy_auto_logout_idle_hm": _format_seconds_hm(_legacy_auto_logout_idle_seconds()),
    }


def _build_login_month_table(login_sessions_qs, work_sessions_qs, date_from, date_to):
    """
    Login table for selected report date filter.

    Date range:
    date_from to date_to

    Columns:
    date, login time, logout time, logout type, total logged hour,
    total work session time of that day.
    """

    login_sessions = (
        login_sessions_qs
        .filter(
            login_at__date__gte=date_from,
            login_at__date__lte=date_to,
        )
        .select_related("user")
        .order_by("login_at")
    )

    work_sessions = (
        work_sessions_qs
        .filter(
            started_at__date__gte=date_from,
            started_at__date__lte=date_to,
        )
        .order_by("started_at")
    )

    work_seconds_by_date = defaultdict(int)

    for session in work_sessions:
        local_started = timezone.localtime(session.started_at)
        session_date = local_started.date()
        work_seconds_by_date[session_date] += int(session.live_work_seconds or 0)

    rows = []

    total_login_seconds = 0
    total_work_seconds = 0

    for login in login_sessions:
        local_login = timezone.localtime(login.login_at)
        effective_logout = _effective_attendance_logout(login)
        local_logout = timezone.localtime(effective_logout) if effective_logout else None

        login_date = local_login.date()

        if local_logout:
            logged_seconds, idle_seconds = _login_session_seconds(
                login,
                local_login,
                local_logout,
            )
        elif login.logout_at is None:
            logged_seconds = max(int((timezone.now() - login.login_at).total_seconds()), 0)
            idle_seconds = 0
        else:
            logged_seconds = 0
            idle_seconds = 0

        day_work_seconds = work_seconds_by_date.get(login_date, 0)

        total_login_seconds += logged_seconds

        rows.append({
            "date": login_date,
            "login_time": local_login,
            "logout_time": local_logout,
            "logout_type": login.get_end_reason_display() if login.end_reason else "Active",
            "logout_reason": login.end_reason or "active",
            "checkout_review_status": login.checkout_review_status,
            "logged_seconds": logged_seconds,
            "logged_hours": _format_seconds_to_hours(logged_seconds),
            "logged_hm": _format_seconds_hm(logged_seconds),
            "idle_seconds": idle_seconds,
            "idle_hm": _format_seconds_hm(idle_seconds),
            "work_seconds": day_work_seconds,
            "work_hours": _format_seconds_to_hours(day_work_seconds),
            "work_hm": _format_seconds_hm(day_work_seconds),
            "ip_address": login.ip_address or "-",
        })

    # If multiple logins are on same date, showing same day work total repeatedly is useful,
    # but total work should not be summed repeatedly.
    total_work_seconds = sum(work_seconds_by_date.values())

    return {
        "rows": rows,
        "total_login_hours": _format_seconds_to_hours(total_login_seconds),
        "total_login_hm": _format_seconds_hm(total_login_seconds),
        "total_work_hours": _format_seconds_to_hours(total_work_seconds),
        "total_work_hm": _format_seconds_hm(total_work_seconds),
    }
