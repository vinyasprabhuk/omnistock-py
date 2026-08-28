"""Unit tests for app/dates.py -- the date-format contract everything else
in the app depends on. See the module docstring for why the exact DB string
format matters (a format drift here breaks date-equality lookups silently)."""
from datetime import datetime, timezone

from app.dates import (
    date_key_to_db, day_before, format_date_key, from_db, now_db,
    parse_date_key, shift_date_key, today_key,
)


def test_today_key_honors_app_today_override(monkeypatch):
    monkeypatch.setenv("APP_TODAY", "2026-03-15")
    assert today_key() == "2026-03-15"


def test_today_key_format_without_override(monkeypatch):
    monkeypatch.delenv("APP_TODAY", raising=False)
    key = today_key()
    assert len(key) == 10
    datetime.strptime(key, "%Y-%m-%d")  # raises if malformed


def test_parse_date_key_is_utc_midnight():
    dt = parse_date_key("2026-08-01")
    assert dt == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_shift_date_key_forward_and_backward():
    assert shift_date_key("2026-08-01", 1) == "2026-08-02"
    assert shift_date_key("2026-08-01", -1) == "2026-07-31"
    assert shift_date_key("2026-01-01", -1) == "2025-12-31"  # year boundary


def test_shift_date_key_month_end_rollover():
    assert shift_date_key("2026-02-28", 1) == "2026-03-01"  # 2026 is not a leap year


def test_format_date_key_human_readable():
    assert format_date_key("2026-08-24") == "24 Aug 2026"


def test_day_before_is_exactly_24_hours():
    dt = parse_date_key("2026-08-15")
    assert day_before(dt) == parse_date_key("2026-08-14")


def test_date_key_to_db_exact_format():
    # This exact 29-char shape is what every real row in the live DB has --
    # any drift here silently breaks {equals: date} lookups.
    assert date_key_to_db("2026-07-01") == "2026-07-01T00:00:00.000+00:00"


def test_now_db_matches_live_row_format():
    result = now_db()
    assert len(result) == 29
    assert result[10] == "T"
    assert result.endswith("+00:00")
    assert result[19] == "."  # millisecond separator present (unlike SQLite's own datetime('now'))


def test_to_db_from_db_round_trip():
    original = "2026-08-24T13:45:30.123+00:00"
    assert date_key_to_db("2026-08-24") != original  # sanity: not accidentally equal
    parsed = from_db(original)
    assert parsed.year == 2026 and parsed.hour == 13 and parsed.microsecond == 123000
