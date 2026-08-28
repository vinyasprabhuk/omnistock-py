"""Port of src/lib/actions/wastageMenu.ts."""
from __future__ import annotations

import sqlite3

from app.dates import now_db
from app.db import new_id
from app.services.meal_periods import MEAL_PERIODS


def get_wastage_menu(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM WastageMenuItem WHERE active = 1 ORDER BY mealPeriod ASC, sortOrder ASC, name ASC"
    ).fetchall()
    items = [dict(r) for r in rows]
    return [{"mealPeriod": mp, "items": [i for i in items if i["mealPeriod"] == mp]} for mp in MEAL_PERIODS]


def get_all_wastage_menu_items(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM WastageMenuItem ORDER BY mealPeriod ASC, sortOrder ASC, name ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def create_wastage_menu_item(conn: sqlite3.Connection, meal_period: str, name: str, is_piece_counted: bool) -> None:
    name = (name or "").strip().upper()
    if meal_period not in MEAL_PERIODS:
        raise ValueError("Invalid meal period")
    if not name:
        raise ValueError("Item name is required")

    max_sort = conn.execute(
        "SELECT MAX(sortOrder) FROM WastageMenuItem WHERE mealPeriod = ?", (meal_period,)
    ).fetchone()[0]
    next_sort = (max_sort if max_sort is not None else -1) + 1

    existing = conn.execute(
        "SELECT id FROM WastageMenuItem WHERE mealPeriod = ? AND name = ?", (meal_period, name)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE WastageMenuItem SET active = 1, isPieceCounted = ? WHERE id = ?",
            (1 if is_piece_counted else 0, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO WastageMenuItem (id, mealPeriod, name, isPieceCounted, sortOrder, active, createdAt) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (new_id(), meal_period, name, 1 if is_piece_counted else 0, next_sort, now_db()),
        )
    conn.commit()


def delete_wastage_menu_item(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute("DELETE FROM WastageMenuItem WHERE id = ?", (item_id,))
    conn.commit()
