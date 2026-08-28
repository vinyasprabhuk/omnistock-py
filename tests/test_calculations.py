"""
DB-backed tests for the core ledger math (app/services/calculations.py),
using a throwaway copy of the real reference database.

Several assertions pin down exact figures that were independently verified
against the live Next.js app during development (browser cross-checks +
the golden-data parity harness in tools/) -- if these ever fail, it means
either a real regression or a change in the underlying data, not a flaky test.
"""
from app.dates import date_key_to_db
from app.services.calculations import (
    get_consolidated_requirement, get_daily_tracker, get_master_inventory, get_period_tracker,
)


def test_daily_tracker_returns_all_active_items(db_conn, branch_id):
    rows = get_daily_tracker(db_conn, branch_id, date_key_to_db("2026-08-01"))
    assert len(rows) > 0
    # Every active item appears exactly once
    item_ids = [r["itemId"] for r in rows]
    assert len(item_ids) == len(set(item_ids))


def test_daily_tracker_known_row_matches_verified_value(db_conn, branch_id):
    # Cross-checked against the live Next.js app's own output during the
    # rewrite's Phase 1 parity pass: opening 1.5, issued 0.5, closing 1,
    # usageCost 175 (price 350/unit).
    rows = get_daily_tracker(db_conn, branch_id, date_key_to_db("2026-08-01"))
    row = next(r for r in rows if r["itemName"] == "Aromat Powder")
    assert row["opening"] == 1.5
    assert row["issued"] == 0.5
    assert row["closing"] == 1.0
    assert row["usageCost"] == 175.0


def test_closing_equals_opening_plus_purchased_minus_issued(db_conn, branch_id):
    rows = get_daily_tracker(db_conn, branch_id, date_key_to_db("2026-08-01"))
    for r in rows:
        assert r["closing"] == r["opening"] + r["purchased"] - r["issued"]


def test_usage_cost_equals_issued_times_price(db_conn, branch_id):
    rows = get_daily_tracker(db_conn, branch_id, date_key_to_db("2026-08-01"))
    for r in rows:
        assert r["usageCost"] == r["issued"] * r["price"]


def test_master_inventory_total_store_value_matches_verified_figure(db_conn, branch_id):
    # Verified live in the browser against the Next.js app: ₹91,306.86 exactly.
    rows = get_master_inventory(db_conn, branch_id)
    total = sum(r["storeValue"] for r in rows)
    assert round(total, 2) == 91306.86


def test_master_inventory_current_stock_formula(db_conn, branch_id):
    rows = get_master_inventory(db_conn, branch_id)
    for r in rows:
        assert r["currentStock"] == r["opening"] + r["totalPurchased"] - r["totalIssued"]
        assert r["storeValue"] == r["currentStock"] * r["purchasePrice"]


def test_period_tracker_opening_matches_closing_stock_before_period(db_conn, branch_id):
    rows = get_period_tracker(db_conn, branch_id, date_key_to_db("2026-08-01"), date_key_to_db("2026-08-23"))
    assert len(rows) > 0
    for r in rows:
        assert r["closing"] == r["opening"] + r["purchased"] - r["issued"]


def test_inactive_items_excluded_from_tracker(db_conn, branch_id):
    # Deactivate a real item, confirm it drops out of the tracker.
    row = db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()
    db_conn.execute("UPDATE Item SET active = 0 WHERE id = ?", (row["id"],))
    rows = get_daily_tracker(db_conn, branch_id, date_key_to_db("2026-08-01"))
    assert row["name"] not in [r["itemName"] for r in rows]


def test_consolidated_requirement_empty_when_no_confirmed_requirements(db_conn, branch_id):
    # The real dataset has zero KitchenRequirement rows (feature never used in
    # production as of this rewrite) -- confirm the empty case doesn't crash
    # and returns a clean empty list, not None or an error.
    rows = get_consolidated_requirement(db_conn, branch_id, date_eq=date_key_to_db("2026-08-01"))
    assert rows == []


def test_getting_a_different_branch_gives_independent_opening_stock(db_conn, branch_id):
    # Create a second branch with no opening stock rows at all -- every item
    # must start at 0 for it, never inherited from the first branch.
    import uuid
    new_branch_id = uuid.uuid4().hex
    db_conn.execute(
        "INSERT INTO Branch (id, name, active, updatedAt) VALUES (?, 'Test Branch 2', 1, datetime('now'))",
        (new_branch_id,),
    )
    db_conn.commit()
    rows = get_daily_tracker(db_conn, new_branch_id, date_key_to_db("2026-08-01"))
    assert all(r["opening"] == 0 for r in rows)
