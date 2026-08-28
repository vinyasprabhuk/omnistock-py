"""
Number formatting helpers, ported to match the live app's display exactly.

Two money formats are used in different places in the original app:
  - money(): plain `n.toFixed(2)` with a Rupee sign, no thousands grouping --
    used on Tracker/Master Inventory (see fmt()/money() in those page.tsx files).
  - money_grouped(): `n.toLocaleString("en-IN", {minimumFractionDigits:2,
    maximumFractionDigits:2})` -- Indian digit grouping (lakh/crore, e.g.
    "1,23,456.78" not "123,456.78") -- used on the Dashboard and its
    ingredient/period tables. Python has no stdlib equivalent, so it's
    hand-written below.
"""
from __future__ import annotations


def fmt(n: float) -> str:
    """Bare integer if n is a whole number, else 2 decimal places."""
    if n == int(n):
        return str(int(n))
    return f"{n:.2f}"


def money(n: float) -> str:
    """Plain 2-decimal money, no thousands grouping -- Tracker/Inventory pages."""
    return f"₹{n:.2f}"


def _indian_group(int_part: str) -> str:
    """'1234567' -> '12,34,567' (last 3 digits, then groups of 2)."""
    neg = int_part.startswith("-")
    if neg:
        int_part = int_part[1:]
    if len(int_part) <= 3:
        grouped = int_part
    else:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    return ("-" if neg else "") + grouped


def money_grouped(n: float) -> str:
    """Rupee-formatted with Indian (lakh/crore) digit grouping, 2 decimal places."""
    sign = "-" if n < 0 else ""
    n = abs(n)
    whole = int(n)
    frac = round((n - whole) * 100)
    if frac == 100:  # rounding carry, e.g. 4.999 -> whole=4 frac=100
        whole += 1
        frac = 0
    return f"₹{sign}{_indian_group(str(whole))}.{frac:02d}"


def pct(n: float | None) -> str:
    """1 decimal place with an explicit sign, or an em-dash for None."""
    if n is None:
        return "—"
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.1f}%"
