"""
Port of src/lib/inventory/spendPeriods.ts.

Shared week/weekend/month boundary math used by both purchase spend and
usage (consumption) spend so the two stay directly comparable. Weeks are
Monday-start. "This week"/"this month" are period-to-date (however many days
have elapsed so far), compared against the FULL previous period.

All boundaries are UTC-midnight datetimes (matching parseDateKey's wire
format), and boundary comparisons are inclusive on both ends.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TypedDict

from app.dates import parse_date_key, today_key

_UTC = timezone.utc


def _add_days(d: datetime, days: int) -> datetime:
    return d + timedelta(days=days)


def _monday_offset(d: datetime) -> int:
    """Monday=0 .. Sunday=6, regardless of Python's Monday=0..Sunday=6 weekday()
    which already matches -- kept as its own function for parity with the
    original's explicit (getUTCDay()+6)%7 remap from Sunday-first."""
    return d.weekday()  # Python's datetime.weekday(): Monday=0 .. Sunday=6 already


def _start_of_week(d: datetime) -> datetime:
    return _add_days(d, -_monday_offset(d))


class PeriodBoundaries(TypedDict):
    thisMonthStart: datetime
    thisMonthEnd: datetime
    lastMonthStart: datetime
    lastMonthEnd: datetime
    thisWeekStart: datetime
    thisWeekEnd: datetime
    lastWeekStart: datetime
    lastWeekEnd: datetime
    thisWeekendStart: datetime
    thisWeekendEnd: datetime
    lastWeekendStart: datetime
    lastWeekendEnd: datetime


def get_period_boundaries(today: datetime | None = None) -> PeriodBoundaries:
    if today is None:
        today = parse_date_key(today_key())

    this_month_start = datetime(today.year, today.month, 1, tzinfo=_UTC)
    # Python's month-1 doesn't auto-normalize into prior year like JS Date.UTC does,
    # so handle the January-rollback explicitly.
    if today.month == 1:
        last_month_start = datetime(today.year - 1, 12, 1, tzinfo=_UTC)
    else:
        last_month_start = datetime(today.year, today.month - 1, 1, tzinfo=_UTC)
    last_month_end = _add_days(this_month_start, -1)

    this_week_start = _start_of_week(today)
    last_week_start = _add_days(this_week_start, -7)
    last_week_end = _add_days(this_week_start, -1)

    # Weekend = Saturday (day 5) + Sunday (day 6) of that Monday-start week.
    this_weekend_start = _add_days(this_week_start, 5)
    this_weekend_end = _add_days(this_week_start, 6)
    last_weekend_start = _add_days(last_week_start, 5)
    last_weekend_end = _add_days(last_week_start, 6)

    return {
        "thisMonthStart": this_month_start,
        "thisMonthEnd": today,  # NOT thisMonthStart+N -- period-to-date, ends today
        "lastMonthStart": last_month_start,
        "lastMonthEnd": last_month_end,
        "thisWeekStart": this_week_start,
        "thisWeekEnd": today,  # NOT thisWeekStart+6 -- period-to-date, ends today
        "lastWeekStart": last_week_start,
        "lastWeekEnd": last_week_end,
        "thisWeekendStart": this_weekend_start,
        "thisWeekendEnd": this_weekend_end,
        "lastWeekendStart": last_weekend_start,
        "lastWeekendEnd": last_weekend_end,
    }


class PeriodComparison(TypedDict):
    thisMonth: float
    lastMonth: float
    monthChangePercent: float | None
    thisWeek: float
    lastWeek: float
    weekChangePercent: float | None
    thisWeekendAvg: float
    lastWeekendAvg: float
    weekendChangePercent: float | None


def _sum_in_range(rows: list[dict], start: datetime, end: datetime) -> float:
    total = 0.0
    for r in rows:
        if start <= r["date"] <= end:
            total += r["spend"]
    return total


def _change_percent(current: float, previous: float) -> float | None:
    return ((current - previous) / previous) * 100 if previous > 0 else None


def compute_period_comparison(rows: list[dict]) -> PeriodComparison:
    """`rows` is a list of {"date": datetime, "spend": float}."""
    b = get_period_boundaries()

    this_month = _sum_in_range(rows, b["thisMonthStart"], b["thisMonthEnd"])
    last_month = _sum_in_range(rows, b["lastMonthStart"], b["lastMonthEnd"])
    this_week = _sum_in_range(rows, b["thisWeekStart"], b["thisWeekEnd"])
    last_week = _sum_in_range(rows, b["lastWeekStart"], b["lastWeekEnd"])
    this_weekend_avg = _sum_in_range(rows, b["thisWeekendStart"], b["thisWeekendEnd"]) / 2
    last_weekend_avg = _sum_in_range(rows, b["lastWeekendStart"], b["lastWeekendEnd"]) / 2

    return {
        "thisMonth": this_month,
        "lastMonth": last_month,
        "monthChangePercent": _change_percent(this_month, last_month),
        "thisWeek": this_week,
        "lastWeek": last_week,
        "weekChangePercent": _change_percent(this_week, last_week),
        "thisWeekendAvg": this_weekend_avg,
        "lastWeekendAvg": last_weekend_avg,
        "weekendChangePercent": _change_percent(this_weekend_avg, last_weekend_avg),
    }
