"""
Wraps the golden-data parity check (tools/parity_dump.py's scenarios) as
real pytest tests, so a numeric regression in the ported business logic
fails a normal `pytest` run instead of requiring someone to remember to run
the standalone harness in tools/.

Uses the SAME golden JSON captured from the live Next.js app (tests/golden/)
as the source of truth, but runs the Python functions against the pristine
reference DB copy (via the shared db_conn fixture) rather than the mutable
instance/dev.db the standalone tools/ scripts use -- so this suite is
self-contained and safe to run anytime without touching the working DB.

Skipped automatically if the golden files were captured on a different
calendar day than "today" (Asia/Kolkata) -- see tools/parity_dump.py's own
caveat: spendThisMonth/period-comparison figures are date-relative and will
legitimately differ across days. Use APP_TODAY to pin the clock for a
deterministic re-run instead of trusting the wall clock.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dates import date_key_to_db, from_db, today_key
from app.services import purchase_analytics as pa
from app.services import usage_analytics as ua
from app.services.calculations import get_daily_tracker, get_master_inventory, get_period_tracker
from app.services.match_item import match_item

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
REL_TOL = 1e-9
ABS_TOL = 1e-9


def _load(name: str):
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text())


def _meta():
    return _load("_meta")


pytestmark = pytest.mark.skipif(not GOLDEN_DIR.exists(), reason="no golden data captured -- see tools/parity_dump.py")


def _assert_close(actual, expected, path=""):
    if isinstance(expected, bool) or isinstance(actual, bool):
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        diff = abs(actual - expected)
        assert diff <= ABS_TOL or diff <= REL_TOL * max(abs(actual), abs(expected)), \
            f"{path}: {actual!r} != {expected!r} (diff={diff!r})"
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual)}"
        assert set(actual.keys()) == set(expected.keys()), f"{path}: key mismatch {set(actual)} vs {set(expected)}"
        for k in expected:
            _assert_close(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), \
            f"{path}: length mismatch {len(actual) if isinstance(actual, list) else '?'} vs {len(expected)}"
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_close(a, e, f"{path}[{i}]")
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


@pytest.fixture()
def golden_meta():
    meta = _meta()
    if today_key() != meta["todayKey"]:
        pytest.skip(
            f"golden captured on {meta['todayKey']}, today is {today_key()} -- "
            f"date-relative figures would legitimately differ; re-run with APP_TODAY={meta['todayKey']} to force"
        )
    return meta


class TestCalculationsParity:
    def test_daily_tracker(self, db_conn, golden_meta):
        golden = _load("daily_tracker")
        for date_key, expected_rows in golden.items():
            actual_rows = get_daily_tracker(db_conn, golden_meta["branchId"], date_key_to_db(date_key))
            _assert_close(actual_rows, expected_rows, f"daily_tracker[{date_key}]")

    def test_master_inventory(self, db_conn, golden_meta):
        golden = _load("master_inventory")
        scenarios = {
            "default_asOf_today": None,
            "asOf_2026_07_31": date_key_to_db("2026-07-31"),
            "asOf_2026_08_23": date_key_to_db("2026-08-23"),
        }
        for key, as_of in scenarios.items():
            actual = get_master_inventory(db_conn, golden_meta["branchId"], as_of)
            _assert_close(actual, golden[key], f"master_inventory[{key}]")

    def test_period_tracker(self, db_conn, golden_meta):
        golden = _load("period_tracker")
        scenarios = {
            "2026-07-01_to_2026-07-31": ("2026-07-01", "2026-07-31"),
            "2026-08-01_to_2026-08-23": ("2026-08-01", "2026-08-23"),
        }
        for key, (frm, to) in scenarios.items():
            actual = get_period_tracker(db_conn, golden_meta["branchId"], date_key_to_db(frm), date_key_to_db(to))
            _assert_close(actual, golden[key], f"period_tracker[{key}]")


class TestPurchaseAnalyticsParity:
    def test_spend_summary_unfiltered(self, db_conn, golden_meta):
        golden = _load("purchase_analytics")
        actual = pa.get_spend_summary(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["spendSummary_unfiltered"], "spendSummary_unfiltered")

    def test_spend_by_ingredient_unfiltered(self, db_conn, golden_meta):
        golden = _load("purchase_analytics")
        actual = pa.get_spend_by_ingredient(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["spendByIngredient_unfiltered"], "spendByIngredient_unfiltered")

    def test_spend_by_supplier(self, db_conn, golden_meta):
        golden = _load("purchase_analytics")
        actual = pa.get_spend_by_supplier(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["spendBySupplier_unfiltered"], "spendBySupplier_unfiltered")

    def test_spend_by_month(self, db_conn, golden_meta):
        golden = _load("purchase_analytics")
        actual = pa.get_spend_by_month(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["spendByMonth_unfiltered"], "spendByMonth_unfiltered")

    def test_purchase_period_comparison(self, db_conn, golden_meta):
        golden = _load("purchase_analytics")
        actual = pa.get_purchase_period_comparison(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["periodComparison"], "periodComparison")


class TestUsageAnalyticsParity:
    def test_usage_summary_unfiltered(self, db_conn, golden_meta):
        golden = _load("usage_analytics")
        actual = ua.get_usage_summary(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["usageSummary_unfiltered"], "usageSummary_unfiltered")

    def test_usage_by_ingredient_unfiltered(self, db_conn, golden_meta):
        golden = _load("usage_analytics")
        actual = ua.get_usage_by_ingredient(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["usageByIngredient_unfiltered"], "usageByIngredient_unfiltered")

    def test_usage_by_month(self, db_conn, golden_meta):
        golden = _load("usage_analytics")
        actual = ua.get_usage_by_month(db_conn, golden_meta["branchId"])
        _assert_close(actual, golden["usageByMonth_unfiltered"], "usageByMonth_unfiltered")


class TestMatchItemParity:
    def test_all_probe_strings(self, db_conn, golden_meta):
        golden = _load("match_item")
        mismatches = []
        for probe in golden:
            actual = match_item(db_conn, probe["input"])
            try:
                _assert_close(actual, probe["result"], f"match_item({probe['input']!r})")
            except AssertionError as e:
                mismatches.append(str(e))
        assert not mismatches, f"{len(mismatches)} match_item mismatch(es):\n" + "\n".join(mismatches[:20])
