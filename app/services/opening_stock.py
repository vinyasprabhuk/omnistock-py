"""Mobile-friendly Opening Stock entry -- a standalone tab (not part of
the financial Master Inventory report, which stays ADMIN/MANAGER/STORE/
VIEWER only) so Kitchen staff can do a physical stock count from a
phone: tap an item tile, enter qty, save. ItemOpeningStock has no date
column (see calculations.py) -- it's a single running seed per
item/branch, same semantics as the existing Excel opening-stock import
this reuses the upsert pattern from.
"""
from __future__ import annotations

import sqlite3

from app.dates import now_db
from app.db import new_id


def get_items_with_opening_stock(conn: sqlite3.Connection, branch_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT i.id AS id, i.name AS name, i.unit AS unit, "
        "COALESCE(ios.qty, 0) AS qty "
        "FROM Item i LEFT JOIN ItemOpeningStock ios ON ios.itemId = i.id AND ios.branchId = ? "
        "WHERE i.active = 1 ORDER BY i.name ASC",
        (branch_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_opening_stock_qty(conn: sqlite3.Connection, item_id: str, branch_id: str, qty: float) -> None:
    if qty < 0:
        raise ValueError("Quantity can't be negative")
    item = conn.execute("SELECT id FROM Item WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if item is None:
        raise ValueError("Item not found")

    existing = conn.execute(
        "SELECT id FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (item_id, branch_id)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE ItemOpeningStock SET qty = ?, updatedAt = ? WHERE id = ?",
            (qty, now_db(), existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO ItemOpeningStock (id, itemId, branchId, qty, updatedAt) VALUES (?, ?, ?, ?, ?)",
            (new_id(), item_id, branch_id, qty, now_db()),
        )
    conn.commit()
