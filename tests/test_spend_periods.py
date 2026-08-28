"""Unit tests for app/services/spend_periods.py -- Monday-start week boundaries,
period-to-date semantics, and the weekend-average (not total) quirk."""
from datetime import datetime, timezone

from app.services.spend_periods import compute_period_comparison, get_period_boundaries

UTC = timezone.utc


def test_week_starts_on_monday():
    # 2026-08-26 is a Wednesday
    today = datetime(2026, 8, 26, tzinfo=UTC)
    b = get_period_boundaries(today)
    assert b["thisWeekStart"] == datetime(2026, 8, 24, tzinfo=UTC)  # the preceding Monday
    assert b["thisWeekStart"].weekday() == 0


def test_week_boundaries_are_period_to_date_not_full_week():
    # thisWeekEnd must be "today", NOT thisWeekStart+6 -- this is the dead-code
    # trap in the original TS (a local var computed then overridden by the
    # returned field). Confirm the Python port didn't reintroduce it.
    today = datetime(2026, 8, 26, tzinfo=UTC)
    b = get_period_boundaries(today)
    assert b["thisWeekEnd"] == today
    assert b["thisMonthEnd"] == today


def test_last_week_is_the_full_prior_week():
    today = datetime(2026, 8, 26, tzinfo=UTC)  # Wednesday, this week starts Mon 24th
    b = get_period_boundaries(today)
    assert b["lastWeekStart"] == datetime(2026, 8, 17, tzinfo=UTC)
    assert b["lastWeekEnd"] == datetime(2026, 8, 23, tzinfo=UTC)  # the Sunday just before this week


def test_month_boundary_handles_january_rollback():
    today = datetime(2026, 1, 15, tzinfo=UTC)
    b = get_period_boundaries(today)
    assert b["lastMonthStart"] == datetime(2025, 12, 1, tzinfo=UTC)
    assert b["thisMonthStart"] == datetime(2026, 1, 1, tzinfo=UTC)


def test_weekend_is_saturday_and_sunday_of_that_week():
    today = datetime(2026, 8, 26, tzinfo=UTC)  # week starts Mon 24th
    b = get_period_boundaries(today)
    assert b["thisWeekendStart"] == datetime(2026, 8, 29, tzinfo=UTC)  # Saturday
    assert b["thisWeekendEnd"] == datetime(2026, 8, 30, tzinfo=UTC)    # Sunday


def test_weekend_figure_is_averaged_not_summed(monkeypatch):
    # Sat + Sun = 1000 total -> averaged over 2 days = 500/day, not 1000.
    import app.services.spend_periods as sp
    original = sp.get_period_boundaries
    monkeypatch.setattr(sp, "get_period_boundaries", lambda: original(datetime(2026, 8, 26, tzinfo=UTC)))
    rows = [
        {"date": datetime(2026, 8, 29, tzinfo=UTC), "spend": 600.0},  # Saturday
        {"date": datetime(2026, 8, 30, tzinfo=UTC), "spend": 400.0},  # Sunday
    ]
    result = compute_period_comparison(rows)
    assert result["thisWeekendAvg"] == 500.0  # (600+400)/2, not 1000


def test_change_percent_none_when_previous_is_zero_or_negative(monkeypatch):
    import app.services.spend_periods as sp
    original = sp.get_period_boundaries
    monkeypatch.setattr(sp, "get_period_boundaries", lambda: original(datetime(2026, 8, 26, tzinfo=UTC)))
    rows = [{"date": datetime(2026, 8, 25, tzinfo=UTC), "spend": 100.0}]
    result = compute_period_comparison(rows)
    # No spend at all in "last week" -> previous is 0 -> None, not division by zero
    assert result["weekChangePercent"] is None
