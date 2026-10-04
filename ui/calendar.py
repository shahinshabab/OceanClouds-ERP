# ui/calendar.py
"""
Shared calendar layout for the event calendar and the work calendar.

A view builds a CalendarRange from the request (which view, which dates),
queries its records for range.start..range.end, turns each record into a
calendar entry dict, and calls range.layout(entries) for the template
context. The templates live in ui/templates/ui/calendar/.

Entry keys:
    date        datetime.date (required)
    title       str (required)
    url         str, empty when the user cannot open the record
    start, end  datetime.time or None (None = all-day)
    tone        "solid" | "outline" | "dashed" | "gray" | "soft" | "danger"
    icon        bootstrap icon class, e.g. "bi-stars"
    meta        list of (icon, text) shown under the title
    status      status label
    mine        True to mark the current user's own work
"""

import calendar as pycalendar
from datetime import date, time, timedelta
from urllib.parse import urlencode

from django.utils import timezone

VIEWS = ("month", "week", "agenda")
AGENDA_DAYS = 30
MONTH_VISIBLE = 4
DAY_START_HOUR = 7
DAY_END_HOUR = 23
DEFAULT_MINUTES = 60
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _minutes(t):
    return t.hour * 60 + t.minute


class CalendarRange:
    def __init__(self, view, anchor, today, params):
        self.view = view if view in VIEWS else "month"
        self.anchor = anchor
        self.today = today
        self.params = params  # other query params (filters) to keep in links

        if self.view == "month":
            first = anchor.replace(day=1)
            last = first.replace(day=pycalendar.monthrange(first.year, first.month)[1])
            self.start = first - timedelta(days=first.weekday())
            self.end = last + timedelta(days=6 - last.weekday())
            self.first, self.last = first, last
            self.prev_anchor = (first - timedelta(days=1)).replace(day=1)
            self.next_anchor = last + timedelta(days=1)
            self.title = first.strftime("%B %Y")
        elif self.view == "week":
            self.start = anchor - timedelta(days=anchor.weekday())
            self.end = self.start + timedelta(days=6)
            self.first, self.last = self.start, self.end
            self.prev_anchor = self.start - timedelta(days=7)
            self.next_anchor = self.start + timedelta(days=7)
            if self.start.month == self.end.month:
                self.title = f"{self.start:%d} – {self.end:%d %B %Y}"
            elif self.start.year == self.end.year:
                self.title = f"{self.start:%d %b} – {self.end:%d %b %Y}"
            else:
                self.title = f"{self.start:%d %b %Y} – {self.end:%d %b %Y}"
        else:
            self.start = anchor
            self.end = anchor + timedelta(days=AGENDA_DAYS - 1)
            self.first, self.last = self.start, self.end
            self.prev_anchor = anchor - timedelta(days=AGENDA_DAYS)
            self.next_anchor = anchor + timedelta(days=AGENDA_DAYS)
            self.title = f"{self.start:%d %b} – {self.end:%d %b %Y}"

    @classmethod
    def from_request(cls, request, keep=(), default_view="month"):
        today = timezone.localdate()
        view = (request.GET.get("view") or default_view).strip()
        raw = (request.GET.get("date") or "").strip()
        anchor = today
        if raw:
            try:
                anchor = date.fromisoformat(raw)
            except ValueError:
                # Old links used ?month=YYYY-MM.
                pass
        month = (request.GET.get("month") or "").strip()
        if not raw and month:
            try:
                year, mon = (int(part) for part in month.split("-", 1))
                anchor = date(year, mon, 1)
            except (TypeError, ValueError):
                pass
        params = {k: request.GET.get(k) for k in keep if request.GET.get(k)}
        return cls(view, anchor, today, params)

    # ------------------------------------------------------------------
    def url(self, view=None, anchor=None, **extra):
        query = dict(self.params)
        query.update({k: v for k, v in extra.items() if v})
        query["view"] = view or self.view
        query["date"] = (anchor or self.anchor).isoformat()
        return "?" + urlencode(query)

    def nav(self):
        return {
            "prev": self.url(anchor=self.prev_anchor),
            "next": self.url(anchor=self.next_anchor),
            "today": self.url(anchor=self.today),
            "views": [
                {"key": key, "label": key.title(), "url": self.url(view=key), "active": key == self.view}
                for key in VIEWS
            ],
            "title": self.title,
            "view": self.view,
            "anchor": self.anchor,
            "filters": self.params,
        }

    # ------------------------------------------------------------------
    def _by_day(self, entries):
        days = {}
        for entry in entries:
            entry.setdefault("tone", "outline")
            entry.setdefault("meta", [])
            entry.setdefault("url", "")
            entry.setdefault("start", None)
            entry.setdefault("end", None)
            day = entry["date"]
            if self.start <= day <= self.end:
                days.setdefault(day, []).append(entry)
        for items in days.values():
            # By kind (events first), then all-day before timed, then time.
            items.sort(key=lambda e: (e.get("order", 0), e["start"] is not None, e["start"] or time.min, e["title"].lower()))
        return days

    def layout(self, entries):
        days = self._by_day(entries)
        context = {
            "cal": self.nav(),
            "cal_total": sum(len(v) for v in days.values()),
        }
        if self.view == "month":
            context["cal_weeks"] = self._month(days)
            context["cal_weekdays"] = WEEKDAY_NAMES
        elif self.view == "week":
            context.update(self._week(days))
        else:
            context["cal_agenda"] = self._agenda(days)
        return context

    def _month(self, days):
        weeks = []
        day = self.start
        while day <= self.end:
            week = []
            for _ in range(7):
                items = days.get(day, [])
                week.append({
                    "date": day,
                    "in_month": day.month == self.first.month,
                    "is_today": day == self.today,
                    "is_past": day < self.today,
                    "is_weekend": day.weekday() >= 5,
                    "items": items[:MONTH_VISIBLE],
                    "more": max(0, len(items) - MONTH_VISIBLE),
                    "count": len(items),
                    "week_url": self.url(view="week", anchor=day),
                    "agenda_url": self.url(view="agenda", anchor=day),
                })
                day += timedelta(days=1)
            weeks.append(week)
        return weeks

    def _week(self, days):
        timed = [e for items in days.values() for e in items if e["start"]]
        start_hour = DAY_START_HOUR
        end_hour = DAY_END_HOUR
        if timed:
            start_hour = min(start_hour, min(e["start"].hour for e in timed))
            latest = max(_minutes(e["end"] or e["start"]) for e in timed)
            end_hour = max(end_hour, min(24, latest // 60 + 1))
        hour_height = 56
        now = timezone.localtime()

        columns = []
        for offset in range(7):
            day = self.start + timedelta(days=offset)
            items = days.get(day, [])
            all_day = [e for e in items if not e["start"]]
            blocks = self._place_blocks([e for e in items if e["start"]], start_hour, hour_height)
            now_top = None
            if day == self.today and start_hour * 60 <= _minutes(now.time()) <= end_hour * 60:
                now_top = (_minutes(now.time()) - start_hour * 60) * hour_height / 60
            columns.append({
                "date": day,
                "is_today": day == self.today,
                "is_weekend": day.weekday() >= 5,
                "all_day": all_day,
                "blocks": blocks,
                "now_top": now_top,
                "day_url": self.url(view="agenda", anchor=day),
            })

        hours = [
            {"label": f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"}
            for h in range(start_hour, end_hour)
        ]
        return {
            "cal_columns": columns,
            "cal_hours": hours,
            "cal_hour_height": hour_height,
            "cal_grid_height": (end_hour - start_hour) * hour_height,
            "cal_has_all_day": any(c["all_day"] for c in columns),
        }

    @staticmethod
    def _place_blocks(items, start_hour, hour_height):
        """Position timed entries and split overlapping ones into lanes."""
        prepared = []
        for entry in items:
            begin = _minutes(entry["start"])
            finish = _minutes(entry["end"]) if entry["end"] and _minutes(entry["end"]) > begin else begin + DEFAULT_MINUTES
            prepared.append([begin, finish, entry])
        prepared.sort(key=lambda p: (p[0], -p[1]))

        # Group entries that overlap into clusters, then give each a lane.
        clusters, current, cluster_end = [], [], -1
        for item in prepared:
            if current and item[0] >= cluster_end:
                clusters.append(current)
                current = []
            current.append(item)
            cluster_end = max(cluster_end, item[1])
        if current:
            clusters.append(current)

        blocks = []
        for cluster in clusters:
            lanes = []
            placed = []
            for begin, finish, entry in cluster:
                for index, lane_end in enumerate(lanes):
                    if lane_end <= begin:
                        lanes[index] = finish
                        lane = index
                        break
                else:
                    lanes.append(finish)
                    lane = len(lanes) - 1
                placed.append((begin, finish, entry, lane))
            width = 100 / len(lanes)
            for begin, finish, entry, lane in placed:
                top = (begin - start_hour * 60) * hour_height / 60
                height = max((finish - begin) * hour_height / 60, 26)
                blocks.append({
                    "entry": entry,
                    "top": round(top, 1),
                    "height": round(height - 2, 1),
                    "left": round(lane * width, 2),
                    "width": round(width, 2),
                    "short": height < 44,
                })
        return blocks

    def _agenda(self, days):
        agenda = []
        for day in sorted(days):
            agenda.append({
                "date": day,
                "is_today": day == self.today,
                "items": days[day],
            })
        return agenda
