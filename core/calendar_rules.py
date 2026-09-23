"""Resolve actual event periods using one explicit application timezone."""
import calendar as month_calendar
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def today_in_timezone() -> date:
    """Return today's date in BOOK_TIMEZONE (UTC unless configured)."""
    return datetime.now(ZoneInfo(os.getenv("BOOK_TIMEZONE", "UTC"))).date()


def event_period(event: dict, year: int) -> tuple[date, date] | None:
    """Resolve exact inclusive dates; weekdays run Monday=0 through Sunday=6."""
    if event.get("enabled", True) is False:
        return None
    rule = event.get("schedule")
    if not rule:
        raise ValueError(f"Event {event.get('event_name')} needs an exact schedule")
    kind = rule["kind"]
    if kind == "dates":
        value = rule.get("years", {}).get(str(year))
        return (date.fromisoformat(value[0]), date.fromisoformat(value[1])) if value else None
    month = int(rule["month"])
    if kind == "month":
        return date(year, month, 1), date(year, month, month_calendar.monthrange(year, month)[1])
    if kind in {"fixed", "range", "week_containing"}:
        start = date(year, month, int(rule["day"]))
    elif kind == "nth_weekday":
        first = date(year, month, 1)
        start = first + timedelta(days=(int(rule["weekday"]) - first.weekday()) % 7 + 7 * (int(rule["nth"]) - 1))
        if start.month != month:
            return None
    elif kind == "last_weekday":
        last = date(year, month, month_calendar.monthrange(year, month)[1])
        start = last - timedelta(days=(last.weekday() - int(rule["weekday"])) % 7)
    else:
        raise ValueError(f"Unsupported event schedule: {kind}")
    if kind == "range":
        end_month, end_day = int(rule["end_month"]), int(rule["end_day"])
        end_year = year + ((end_month, end_day) < (month, int(rule["day"])))
        return start, date(end_year, end_month, end_day)
    if kind == "week_containing":
        start -= timedelta(days=(start.weekday() - int(rule.get("week_start", 6))) % 7)
    duration = int(rule.get("duration_days", 7 if kind == "week_containing" else 1))
    if not 1 <= duration <= 366:
        raise ValueError("Event duration must be between 1 and 366 days")
    return start, start + timedelta(days=duration - 1)


def find_active_events(calendar: dict, *, today: date | None = None) -> list[dict]:
    """Return only events whose inclusive period contains the application date."""
    reference = today or today_in_timezone()
    active = []
    for event in calendar.get("events", []):
        for year in (reference.year - 1, reference.year):
            period = event_period(event, year)
            if period and period[0] <= reference <= period[1]:
                active.append({**event, "occurs_on": period[0].isoformat(),
                               "ends_on": period[1].isoformat(), "days_away": 0})
                break
    return sorted(active, key=lambda item: (item["occurs_on"] != reference.isoformat(), item["event_name"]))


def find_events_in_window(calendar: dict, *, today: date | None = None, days: int = 30) -> list[dict]:
    """Find event periods overlapping today through today+days, including year rollover."""
    reference = today or today_in_timezone()
    end = reference + timedelta(days=days)
    events = []
    for event in calendar.get('events', []):
        for year in range(reference.year - 1, end.year + 1):
            period = event_period(event, year)
            if period and period[0] <= end and period[1] >= reference and event.get('theme_angles'):
                events.append({**event, 'occurs_on': period[0].isoformat(),
                               'ends_on': period[1].isoformat(),
                               'days_away': max(0, (period[0] - reference).days)})
    return events
