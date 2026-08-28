"""Port of src/lib/inventory/departments.ts -- case-insensitive find-or-create."""
from __future__ import annotations

import sqlite3

from app.db import new_id


def find_or_create_department(conn: sqlite3.Connection, name: str) -> dict:
    trimmed = name.strip()
    key = trimmed.upper()
    row = conn.execute(
        "SELECT id, name FROM Department WHERE UPPER(name) = ?", (key,)
    ).fetchone()
    if row:
        return dict(row)
    dept_id = new_id()
    conn.execute("INSERT INTO Department (id, name, active) VALUES (?, ?, 1)", (dept_id, trimmed))
    conn.commit()
    return {"id": dept_id, "name": trimmed}
