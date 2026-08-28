"""Port of src/lib/actions/production.ts (thin wrapper over quantity_log.py)."""
from __future__ import annotations

import sqlite3

from app.services import quantity_log


def create_production(conn: sqlite3.Connection, user_id: str, branch_id: str, date_key: str,
                       meal_period: str | None, description: str, weight: float | None, unit: str,
                       pieces: int | None, photo_bytes: bytes, photo_filename: str, photo_mime_type: str | None) -> str:
    return quantity_log.create_entry(conn, "ProductionLog", "PRODUCTION_LOGGED", user_id, branch_id, date_key,
                                      meal_period, description, weight, unit, pieces,
                                      photo_bytes, photo_filename, photo_mime_type)


def get_production_for_date(conn: sqlite3.Connection, branch_id: str, date_key: str) -> list[dict]:
    return quantity_log.get_for_date(conn, "ProductionLog", branch_id, date_key)


def delete_production(conn: sqlite3.Connection, entry_id: str) -> None:
    quantity_log.delete_entry(conn, "ProductionLog", entry_id)


def get_branch_id(conn: sqlite3.Connection, entry_id: str) -> str | None:
    return quantity_log.get_branch_id(conn, "ProductionLog", entry_id)
