"""
Port of src/lib/date.ts.

All dates in this app are keyed by "YYYY-MM-DD" strings representing a
calendar day in the restaurant's local timezone (Asia/Kolkata), not the
server's or browser's. Using UTC would flip "today" over at 5:30am IST
instead of midnight -- wrong for a restaurant in India.

Asia/Kolkata has observed no DST since 1945, so a fixed UTC+05:30 offset is
exactly equivalent to zoneinfo.ZoneInfo("Asia/Kolkata") for this app, forever
-- and it has zero dependency (no tzdata needed), unlike zoneinfo on some
minimal Python builds.

Stored/compared as UTC-midnight datetimes, written to the DB in the exact
29-character "YYYY-MM-DDT00:00:00.000+00:00" format the live data uses.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

APP_OFFSET = timezone(timedelta(hours=5, minutes=30))
_UTC = timezone.utc


def today_key() -> str:
    """
    Today's calendar date in Asia/Kolkata, as 'YYYY-MM-DD'.

    Honors an APP_TODAY=YYYY-MM-DD env override for reproducible local
    testing/parity runs (period-comparison figures otherwise change daily).
    """
    override = os.environ.get("APP_TODAY")
    if override:
        return override
    return datetime.now(APP_OFFSET).strftime("%Y-%m-%d")


def parse_date_key(key: str) -> datetime:
    """'YYYY-MM-DD' -> UTC-midnight datetime (matches parseDateKey)."""
    y, m, d = (int(p) for p in key.split("-"))
    return datetime(y, m, d, tzinfo=_UTC)


def format_date_key(key: str) -> str:
    """'YYYY-MM-DD' -> human-readable 'DD Mon YYYY', e.g. '24 Aug 2026'."""
    dt = parse_date_key(key)
    return dt.strftime("%d %b %Y")


def shift_date_key(key: str, days: int) -> str:
    """Add/subtract whole days (UTC-safe), returning a new 'YYYY-MM-DD' key."""
    dt = parse_date_key(key) + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def day_before(dt: datetime) -> datetime:
    """
    Port of calculations.ts's dayBefore(): one calendar day earlier.

    The original JS uses local-time setDate/getDate (not UTC-safe math), but
    since it's only ever called on Dates that are already UTC-midnight day
    boundaries, this is equivalent in practice. The Python port uses
    unambiguous UTC-safe arithmetic to guarantee equivalence rather than
    reproducing the local-time-dependent JS behavior.
    """
    return dt - timedelta(days=1)


DB_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.{ms}+00:00"


def to_db(dt: datetime) -> str:
    """
    Format a (possibly naive, assumed-UTC) datetime into the exact 29-char
    string format found in the live DB: 'YYYY-MM-DDTHH:MM:SS.mmm+00:00'.

    Python's dt.isoformat() omits milliseconds when they're zero and uses a
    different UTC suffix -- this must NOT be used for DB writes, since
    date-equality lookups depend on the exact string format matching.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(_UTC).replace(tzinfo=None)
    ms = f"{dt.microsecond // 1000:03d}"
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+00:00")


def from_db(s: str) -> datetime:
    """Parse the DB's 'YYYY-MM-DDTHH:MM:SS.mmm+00:00' format back to a UTC datetime."""
    # datetime.fromisoformat handles this exact shape directly in Python 3.11+;
    # for broad compatibility, parse manually.
    date_part, rest = s.split("T")
    time_part, offset = rest[:-6], rest[-6:]
    if offset != "+00:00":
        raise ValueError(f"unexpected non-UTC offset in DB datetime: {s!r}")
    hh, mm, ss_ms = time_part.split(":")
    ss, ms = ss_ms.split(".")
    y, mo, d = (int(p) for p in date_part.split("-"))
    return datetime(y, mo, d, int(hh), int(mm), int(ss), int(ms) * 1000, tzinfo=_UTC)


def date_key_to_db(key: str) -> str:
    """Convenience: 'YYYY-MM-DD' -> DB-format UTC-midnight string directly."""
    return to_db(parse_date_key(key))


def now_db() -> str:
    """
    Current instant in the exact DB timestamp format, for createdAt/updatedAt/
    confirmedAt columns. NEVER use SQLite's own datetime('now') for these --
    it produces 'YYYY-MM-DD HH:MM:SS' (space separator, no ms, no offset),
    which silently diverges from every existing row's format and would fail
    tools/verify_schema.py's format check on the very next run.
    """
    return to_db(datetime.now(_UTC))
