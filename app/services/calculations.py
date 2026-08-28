"""
Port of src/lib/inventory/calculations.ts.

No stored "current stock" anywhere -- everything is SUM() over the three
append-only transaction tables (Purchase/PurchaseItem, StockIssue/
StockIssueItem, KitchenRequirement/KitchenRequirementItem), scoped to
(item, branch, date). Stock Issue is what reduces stock; Kitchen Requirement
is informational only (requesting != consuming) and is additionally filtered
to confirmed requirements only.

closing(date) = openingSeed(branch) + purchased(<=date) - issued(<=date), so
"opening" for any date is just closing(date - 1 day) -- no day-by-day walk
needed.

Implementation note: the original TypeScript issues one aggregate query per
item (via Promise.all across items). This port instead issues one GROUP BY
query per transaction table covering ALL items at once and looks values up
from the resulting dict -- mathematically identical results (SUM is the same
regardless of whether it's computed per-item or via GROUP BY), just without
the N-queries-per-item pattern, which matters more in Python's sequential
sqlite3 than it did with JS's concurrent Promise.all.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TypedDict

from app.dates import day_before, from_db, parse_date_key, to_db, today_key


def get_opening_stock_map(conn: sqlite3.Connection, branch_id: str) -> dict[str, float]:
    rows = conn.execute(
        'SELECT itemId, qty FROM ItemOpeningStock WHERE branchId = ?', (branch_id,)
    ).fetchall()
    return {r["itemId"]: float(r["qty"]) for r in rows}


def _get_active_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        'SELECT id, name, unit, purchasePrice FROM Item WHERE active = 1 ORDER BY name ASC'
    ).fetchall()


# --- Per-item cumulative sums (used by closingStock, which needs a single
# item's total up to a given date) ---

def sum_purchased(conn: sqlite3.Connection, item_id: str, branch_id: str,
                   date_eq: str | None = None, date_lte: str | None = None,
                   date_gte: str | None = None) -> float:
    conditions = ["pi.itemId = ?", "p.branchId = ?"]
    params: list = [item_id, branch_id]
    if date_eq is not None:
        conditions.append("p.date = ?"); params.append(date_eq)
    if date_lte is not None:
        conditions.append("p.date <= ?"); params.append(date_lte)
    if date_gte is not None:
        conditions.append("p.date >= ?"); params.append(date_gte)
    sql = (
        "SELECT COALESCE(SUM(pi.qty), 0) FROM PurchaseItem pi "
        "JOIN Purchase p ON p.id = pi.purchaseId "
        f"WHERE {' AND '.join(conditions)}"
    )
    return float(conn.execute(sql, params).fetchone()[0] or 0)


def sum_issued(conn: sqlite3.Connection, item_id: str, branch_id: str,
               date_eq: str | None = None, date_lte: str | None = None,
               date_gte: str | None = None) -> float:
    conditions = ["si.itemId = ?", "s.branchId = ?"]
    params: list = [item_id, branch_id]
    if date_eq is not None:
        conditions.append("s.date = ?"); params.append(date_eq)
    if date_lte is not None:
        conditions.append("s.date <= ?"); params.append(date_lte)
    if date_gte is not None:
        conditions.append("s.date >= ?"); params.append(date_gte)
    sql = (
        "SELECT COALESCE(SUM(si.qty), 0) FROM StockIssueItem si "
        "JOIN StockIssue s ON s.id = si.stockIssueId "
        f"WHERE {' AND '.join(conditions)}"
    )
    return float(conn.execute(sql, params).fetchone()[0] or 0)


def sum_kitchen_requirement(conn: sqlite3.Connection, item_id: str, branch_id: str,
                             date_eq: str | None = None, date_lte: str | None = None,
                             date_gte: str | None = None) -> float:
    conditions = ["kri.matchedItemId = ?", "kr.branchId = ?", "kr.confirmedAt IS NOT NULL"]
    params: list = [item_id, branch_id]
    if date_eq is not None:
        conditions.append("kr.date = ?"); params.append(date_eq)
    if date_lte is not None:
        conditions.append("kr.date <= ?"); params.append(date_lte)
    if date_gte is not None:
        conditions.append("kr.date >= ?"); params.append(date_gte)
    sql = (
        "SELECT COALESCE(SUM(kri.qty), 0) FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId "
        f"WHERE {' AND '.join(conditions)}"
    )
    return float(conn.execute(sql, params).fetchone()[0] or 0)


def closing_stock(conn: sqlite3.Connection, item_id: str, branch_id: str,
                   opening_seed: float, date_db: str) -> float:
    """Closing stock as of end-of-day `date_db` (DB-format string), inclusive."""
    purchased = sum_purchased(conn, item_id, branch_id, date_lte=date_db)
    issued = sum_issued(conn, item_id, branch_id, date_lte=date_db)
    return opening_seed + purchased - issued


# --- Bulk grouped sums across all items (used by getDailyTracker /
# getPeriodTracker / getMasterInventory, which need every item's total) ---

def _grouped_sum(conn: sqlite3.Connection, table: str, join_table: str, join_col: str,
                  item_col: str, branch_id: str,
                  date_eq: str | None = None, date_lte: str | None = None,
                  date_gte: str | None = None,
                  extra_where: str = "") -> dict[str, float]:
    conditions = [f"j.branchId = ?"]
    params: list = [branch_id]
    if date_eq is not None:
        conditions.append("j.date = ?"); params.append(date_eq)
    if date_lte is not None:
        conditions.append("j.date <= ?"); params.append(date_lte)
    if date_gte is not None:
        conditions.append("j.date >= ?"); params.append(date_gte)
    if extra_where:
        conditions.append(extra_where)
    sql = (
        f"SELECT t.{item_col} AS itemId, COALESCE(SUM(t.qty), 0) AS total "
        f"FROM {table} t JOIN {join_table} j ON j.id = t.{join_col} "
        f"WHERE {' AND '.join(conditions)} GROUP BY t.{item_col}"
    )
    return {r["itemId"]: float(r["total"]) for r in conn.execute(sql, params).fetchall()}


def _bulk_purchased(conn, branch_id, **kw) -> dict[str, float]:
    return _grouped_sum(conn, "PurchaseItem", "Purchase", "purchaseId", "itemId", branch_id, **kw)


def _bulk_issued(conn, branch_id, **kw) -> dict[str, float]:
    return _grouped_sum(conn, "StockIssueItem", "StockIssue", "stockIssueId", "itemId", branch_id, **kw)


def _bulk_kitchen_requirement(conn, branch_id, **kw) -> dict[str, float]:
    return _grouped_sum(
        conn, "KitchenRequirementItem", "KitchenRequirement", "requirementId", "matchedItemId",
        branch_id, extra_where="j.confirmedAt IS NOT NULL", **kw,
    )


def _bulk_closing_stock(conn: sqlite3.Connection, branch_id: str,
                         opening_map: dict[str, float], date_db: str) -> dict[str, float]:
    purchased = _bulk_purchased(conn, branch_id, date_lte=date_db)
    issued = _bulk_issued(conn, branch_id, date_lte=date_db)
    item_ids = set(opening_map) | set(purchased) | set(issued)
    return {
        iid: opening_map.get(iid, 0.0) + purchased.get(iid, 0.0) - issued.get(iid, 0.0)
        for iid in item_ids
    }


class DailyTrackerRow(TypedDict):
    itemId: str
    itemName: str
    unit: str
    price: float
    opening: float
    purchased: float
    kitchenRequirement: float
    issued: float
    closing: float
    usageCost: float


def get_daily_tracker(conn: sqlite3.Connection, branch_id: str, date_db: str) -> list[DailyTrackerRow]:
    items = _get_active_items(conn)
    opening_map = get_opening_stock_map(conn, branch_id)
    prev_date_db = to_db(day_before(from_db(date_db)))

    closing_prev = _bulk_closing_stock(conn, branch_id, opening_map, prev_date_db)
    purchased_today = _bulk_purchased(conn, branch_id, date_eq=date_db)
    kr_today = _bulk_kitchen_requirement(conn, branch_id, date_eq=date_db)
    issued_today = _bulk_issued(conn, branch_id, date_eq=date_db)

    rows: list[DailyTrackerRow] = []
    for item in items:
        item_id = item["id"]
        price = float(item["purchasePrice"])
        opening = closing_prev.get(item_id, 0.0)
        purchased = purchased_today.get(item_id, 0.0)
        kitchen_requirement = kr_today.get(item_id, 0.0)
        issued = issued_today.get(item_id, 0.0)
        closing = opening + purchased - issued
        rows.append({
            "itemId": item_id, "itemName": item["name"], "unit": item["unit"], "price": price,
            "opening": opening, "purchased": purchased, "kitchenRequirement": kitchen_requirement,
            "issued": issued, "closing": closing, "usageCost": issued * price,
        })
    return rows


class PeriodTrackerRow(TypedDict):
    itemId: str
    itemName: str
    unit: str
    price: float
    opening: float
    purchased: float
    kitchenRequirement: float
    issued: float
    closing: float
    usageCost: float


def get_period_tracker(conn: sqlite3.Connection, branch_id: str,
                        from_db_str: str, to_db_str: str) -> list[PeriodTrackerRow]:
    items = _get_active_items(conn)
    opening_map = get_opening_stock_map(conn, branch_id)
    prev_date_db = to_db(day_before(from_db(from_db_str)))

    opening_at_start = _bulk_closing_stock(conn, branch_id, opening_map, prev_date_db)
    purchased_window = _bulk_purchased(conn, branch_id, date_gte=from_db_str, date_lte=to_db_str)
    kr_window = _bulk_kitchen_requirement(conn, branch_id, date_gte=from_db_str, date_lte=to_db_str)
    issued_window = _bulk_issued(conn, branch_id, date_gte=from_db_str, date_lte=to_db_str)

    rows: list[PeriodTrackerRow] = []
    for item in items:
        item_id = item["id"]
        price = float(item["purchasePrice"])
        opening = opening_at_start.get(item_id, 0.0)
        purchased = purchased_window.get(item_id, 0.0)
        kitchen_requirement = kr_window.get(item_id, 0.0)
        issued = issued_window.get(item_id, 0.0)
        closing = opening + purchased - issued
        rows.append({
            "itemId": item_id, "itemName": item["name"], "unit": item["unit"], "price": price,
            "opening": opening, "purchased": purchased, "kitchenRequirement": kitchen_requirement,
            "issued": issued, "closing": closing, "usageCost": issued * price,
        })
    return rows


class MasterInventoryRow(TypedDict):
    itemId: str
    itemName: str
    unit: str
    purchasePrice: float
    opening: float
    totalPurchased: float
    totalKitchenRequirement: float
    totalIssued: float
    currentStock: float
    usageCost: float
    storeValue: float


def get_master_inventory(conn: sqlite3.Connection, branch_id: str,
                          as_of_db: str | None = None) -> list[MasterInventoryRow]:
    """`as_of_db` defaults to today (DB-format UTC-midnight string)."""
    if as_of_db is None:
        as_of_db = to_db(parse_date_key(today_key()))

    items = _get_active_items(conn)
    opening_map = get_opening_stock_map(conn, branch_id)

    total_purchased = _bulk_purchased(conn, branch_id, date_lte=as_of_db)
    total_kr = _bulk_kitchen_requirement(conn, branch_id, date_lte=as_of_db)
    total_issued = _bulk_issued(conn, branch_id, date_lte=as_of_db)

    rows: list[MasterInventoryRow] = []
    for item in items:
        item_id = item["id"]
        price = float(item["purchasePrice"])
        opening_seed = opening_map.get(item_id, 0.0)
        purchased = total_purchased.get(item_id, 0.0)
        kr = total_kr.get(item_id, 0.0)
        issued = total_issued.get(item_id, 0.0)
        current_stock = opening_seed + purchased - issued
        rows.append({
            "itemId": item_id, "itemName": item["name"], "unit": item["unit"],
            "purchasePrice": price, "opening": opening_seed, "totalPurchased": purchased,
            "totalKitchenRequirement": kr, "totalIssued": issued, "currentStock": current_stock,
            "usageCost": issued * price, "storeValue": current_stock * price,
        })
    return rows


class ConsolidatedRequirementRow(TypedDict):
    itemId: str
    itemName: str
    unit: str
    total: float
    byDepartment: list[dict]


def get_consolidated_requirement(conn: sqlite3.Connection, branch_id: str,
                                  date_eq: str | None = None, date_lte: str | None = None,
                                  date_gte: str | None = None) -> list[ConsolidatedRequirementRow]:
    conditions = ["kr.branchId = ?", "kr.confirmedAt IS NOT NULL", "kri.matchedItemId IS NOT NULL"]
    params: list = [branch_id]
    if date_eq is not None:
        conditions.append("kr.date = ?"); params.append(date_eq)
    if date_lte is not None:
        conditions.append("kr.date <= ?"); params.append(date_lte)
    if date_gte is not None:
        conditions.append("kr.date >= ?"); params.append(date_gte)
    sql = (
        "SELECT kri.qty AS qty, i.id AS itemId, i.name AS itemName, i.unit AS unit, "
        "d.name AS departmentName "
        "FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId "
        "JOIN Item i ON i.id = kri.matchedItemId "
        "JOIN Department d ON d.id = kri.departmentId "
        f"WHERE {' AND '.join(conditions)}"
    )
    rows = conn.execute(sql, params).fetchall()

    by_item: dict[str, ConsolidatedRequirementRow] = {}
    for row in rows:
        item_id = row["itemId"]
        entry = by_item.setdefault(item_id, {
            "itemId": item_id, "itemName": row["itemName"], "unit": row["unit"],
            "total": 0.0, "byDepartment": [],
        })
        qty = float(row["qty"])
        entry["total"] += qty
        dept_name = row["departmentName"]
        existing = next((d for d in entry["byDepartment"] if d["departmentName"] == dept_name), None)
        if existing:
            existing["qty"] += qty
        else:
            entry["byDepartment"].append({"departmentName": dept_name, "qty": qty})

    return sorted(by_item.values(), key=lambda r: r["itemName"])
