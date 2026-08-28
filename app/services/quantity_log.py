"""
Shared implementation for Wastage and ProductionLog -- identical schemas,
identical validation, identical audit-log shape (matching the original
wastage.ts / production.ts, which are near-duplicates of each other).
Neither is wired into the stock ledger (informational/accountability logs
only) -- keep it that way.
"""
from __future__ import annotations

import sqlite3

from app.dates import date_key_to_db, now_db
from app.db import new_id
from app.services import audit, storage


def create_entry(conn: sqlite3.Connection, table: str, audit_action: str, user_id: str, branch_id: str,
                  date_key: str, meal_period: str | None, description: str, weight: float | None,
                  unit: str, pieces: int | None, photo_bytes: bytes, photo_filename: str,
                  photo_mime_type: str | None) -> str:
    description = (description or "").strip()
    if not date_key:
        raise ValueError("Date is required")
    if not description:
        raise ValueError("Description is required")
    if pieces is None and (weight is None or weight <= 0):
        raise ValueError("Enter a valid weight")
    if pieces is not None and (pieces < 0 or pieces != int(pieces)):
        raise ValueError("Enter a valid pieces count")
    if not photo_bytes:
        raise ValueError("Photo is required")

    saved = storage.save(photo_bytes, photo_filename)
    entry_id = new_id()
    conn.execute(
        f"INSERT INTO {table} (id, date, branchId, mealPeriod, description, weight, unit, pieces, "
        f"photoPath, photoMimeType, createdById, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_id, date_key_to_db(date_key), branch_id, meal_period, description, weight,
         unit or "KG", pieces, saved["filePath"], photo_mime_type or "image/jpeg", user_id, now_db()),
    )
    audit.write(conn, user_id, branch_id, audit_action, table, entry_id,
                {"description": description, "weight": weight, "unit": unit, "pieces": pieces})
    conn.commit()
    return entry_id


def get_for_date(conn: sqlite3.Connection, table: str, branch_id: str, date_key: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT t.*, u.name AS createdByName FROM {table} t "
        f"JOIN User u ON u.id = t.createdById "
        f"WHERE t.branchId = ? AND t.date = ? ORDER BY t.createdAt DESC",
        (branch_id, date_key_to_db(date_key)),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_entry(conn: sqlite3.Connection, table: str, entry_id: str) -> None:
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))
    conn.commit()


def get_branch_id(conn: sqlite3.Connection, table: str, entry_id: str) -> str | None:
    row = conn.execute(f"SELECT branchId FROM {table} WHERE id = ?", (entry_id,)).fetchone()
    return row["branchId"] if row else None
