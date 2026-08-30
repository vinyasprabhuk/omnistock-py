"""
Workstation Photos: department leads log a photo of their station. Rolling
monthly log, not an indefinite history -- each new capture purges that
department's entries from any prior month, per the user's explicit choice
("keep monthly data and then override").
"""
from __future__ import annotations

import sqlite3

from app.dates import now_db
from app.db import new_id
from app.services import audit, storage


def create_photo(conn: sqlite3.Connection, user_id: str, branch_id: str, department_id: str,
                  photo_bytes: bytes, photo_filename: str, photo_mime_type: str | None) -> str:
    if not photo_bytes:
        raise ValueError("Photo is required")

    saved = storage.save(photo_bytes, photo_filename)
    entry_id = new_id()
    created_at = now_db()
    conn.execute(
        "INSERT INTO WorkstationPhoto (id, branchId, departmentId, photoPath, photoMimeType, "
        "createdById, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entry_id, branch_id, department_id, saved["filePath"],
         photo_mime_type or "image/jpeg", user_id, created_at),
    )

    current_month = created_at[:7]  # "YYYY-MM" prefix of the DB timestamp format
    conn.execute(
        "DELETE FROM WorkstationPhoto WHERE departmentId = ? AND substr(createdAt, 1, 7) != ?",
        (department_id, current_month),
    )

    audit.write(conn, user_id, branch_id, "WORKSTATION_PHOTO_LOGGED", "WorkstationPhoto", entry_id,
                {"departmentId": department_id})
    conn.commit()
    return entry_id


def get_for_department(conn: sqlite3.Connection, department_id: str, month_key: str | None = None) -> list[dict]:
    month_key = month_key or now_db()[:7]
    rows = conn.execute(
        "SELECT p.*, u.name AS createdByName FROM WorkstationPhoto p "
        "JOIN User u ON u.id = p.createdById "
        "WHERE p.departmentId = ? AND substr(p.createdAt, 1, 7) = ? "
        "ORDER BY p.createdAt DESC",
        (department_id, month_key),
    ).fetchall()
    return [dict(r) for r in rows]


def get_branch_id(conn: sqlite3.Connection, entry_id: str) -> str | None:
    row = conn.execute("SELECT branchId FROM WorkstationPhoto WHERE id = ?", (entry_id,)).fetchone()
    return row["branchId"] if row else None
