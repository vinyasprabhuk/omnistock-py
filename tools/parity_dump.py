"""
Runs the Python business-logic port against instance/dev.db and writes JSON
in the same shape as the Next.js app's scripts/dump-golden.mjs output, for
tools/parity_check.py to diff.

Usage: python3 tools/parity_dump.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_connection
from app.dates import date_key_to_db, today_key
from app.services import calculations as calc
from app.services import purchase_analytics as pa
from app.services import usage_analytics as ua
from app.services.match_item import match_item

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "parity_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def write(name: str, data) -> None:
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"wrote {path}")


def main() -> None:
    conn = get_connection()
    meta = json.loads((GOLDEN_DIR / "_meta.json").read_text())
    branch_id = meta["branchId"]

    print(f"Using branch: {meta['branchName']} ({branch_id})")
    print(f"today_key() = {today_key()}  (golden captured at todayKey()={meta['todayKey']})")
    if today_key() != meta["todayKey"]:
        print("WARNING: today's date differs from golden capture date -- "
              "period-comparison fields (spendThisMonth etc) WILL legitimately "
              "differ. Not a bug unless everything else also mismatches.")

    departments = [r["name"] for r in conn.execute("SELECT name FROM Department WHERE active = 1")]

    # --- Daily tracker ---
    daily_dates = ["2026-07-01", "2026-07-15", "2026-07-31", "2026-08-01", "2026-08-23", "2026-09-15"]
    write("daily_tracker", {k: calc.get_daily_tracker(conn, branch_id, date_key_to_db(k)) for k in daily_dates})

    # --- Period tracker ---
    write("period_tracker", {
        "2026-07-01_to_2026-07-31": calc.get_period_tracker(conn, branch_id, date_key_to_db("2026-07-01"), date_key_to_db("2026-07-31")),
        "2026-08-01_to_2026-08-23": calc.get_period_tracker(conn, branch_id, date_key_to_db("2026-08-01"), date_key_to_db("2026-08-23")),
        "2026-07-01_to_2026-08-23": calc.get_period_tracker(conn, branch_id, date_key_to_db("2026-07-01"), date_key_to_db("2026-08-23")),
    })

    # --- Master inventory ---
    write("master_inventory", {
        "default_asOf_today": calc.get_master_inventory(conn, branch_id),
        "asOf_2026_07_31": calc.get_master_inventory(conn, branch_id, date_key_to_db("2026-07-31")),
        "asOf_2026_08_23": calc.get_master_inventory(conn, branch_id, date_key_to_db("2026-08-23")),
    })

    # --- Consolidated requirement ---
    write("consolidated_requirement", {
        "2026-08-01": calc.get_consolidated_requirement(conn, branch_id, date_eq=date_key_to_db("2026-08-01")),
    })

    # --- Purchase analytics ---
    from app.dates import from_db
    range1 = {"from": from_db(date_key_to_db("2026-07-01")), "to": from_db(date_key_to_db("2026-07-31"))}
    range2 = {"from": from_db(date_key_to_db("2026-08-01")), "to": from_db(date_key_to_db("2026-08-23"))}

    purchase = {
        "spendSummary_unfiltered": pa.get_spend_summary(conn, branch_id),
        "spendSummary_july": pa.get_spend_summary(conn, branch_id, range1),
        "spendSummary_aug": pa.get_spend_summary(conn, branch_id, range2),
        "spendByIngredient_unfiltered": pa.get_spend_by_ingredient(conn, branch_id),
        "spendByIngredient_july": pa.get_spend_by_ingredient(conn, branch_id, range1),
        "spendByDepartment_unfiltered": pa.get_spend_by_department(conn, branch_id),
        "spendByDepartment_july": pa.get_spend_by_department(conn, branch_id, range1),
        "spendBySupplier_unfiltered": pa.get_spend_by_supplier(conn, branch_id),
        "spendByBranch_unfiltered": pa.get_spend_by_branch(conn),
        "spendByMonth_unfiltered": pa.get_spend_by_month(conn, branch_id),
        "periodComparison": pa.get_purchase_period_comparison(conn, branch_id),
    }
    for dept in departments:
        purchase[f"spendByDepartment__{dept}"] = pa.get_spend_by_department(conn, branch_id, None, dept)
    write("purchase_analytics", purchase)

    # --- Usage analytics ---
    usage = {
        "usageSummary_unfiltered": ua.get_usage_summary(conn, branch_id),
        "usageSummary_july": ua.get_usage_summary(conn, branch_id, range1),
        "usageSummary_aug": ua.get_usage_summary(conn, branch_id, range2),
        "usageByIngredient_unfiltered": ua.get_usage_by_ingredient(conn, branch_id),
        "usageByIngredient_july": ua.get_usage_by_ingredient(conn, branch_id, range1),
        "usageByDepartment_unfiltered": ua.get_usage_by_department(conn, branch_id),
        "usageByDepartment_july": ua.get_usage_by_department(conn, branch_id, range1),
        "usageByBranch_unfiltered": ua.get_usage_by_branch(conn),
        "usageByMonth_unfiltered": ua.get_usage_by_month(conn, branch_id),
        "periodComparison": ua.get_usage_period_comparison(conn, branch_id),
    }
    write("usage_analytics", usage)

    # --- matchItem: re-run on the SAME inputs the golden used, for a direct diff ---
    golden_match = json.loads((GOLDEN_DIR / "match_item.json").read_text())
    match_results = []
    for probe in golden_match:
        result = match_item(conn, probe["input"])
        match_results.append({"input": probe["input"], "expectedItemName": probe["expectedItemName"], "result": result})
    write("match_item", match_results)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
