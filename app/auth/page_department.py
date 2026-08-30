"""
Department-scoped counterpart to page_branch.py, for the Workstation Photos
tab. DEPARTMENT_LEAD is locked to their assigned department (no query-param
override); ADMIN gets a sensible default (first active department) with an
optional ?departmentId= override, matching page_resolve_branch's shape.
"""
from __future__ import annotations

import sqlite3


def page_resolve_department(conn: sqlite3.Connection, user: dict,
                             requested_department_id: str | None = None) -> dict:
    role = user["role"]
    department_id = user.get("departmentId")

    if role != "ADMIN":
        if not department_id:
            raise ValueError("User has no assigned department")
        row = conn.execute("SELECT id, name FROM Department WHERE id = ?", (department_id,)).fetchone()
        if row is None:
            raise ValueError(f"Department not found: {department_id}")
        return {"departmentId": row["id"], "departmentName": row["name"]}

    if requested_department_id:
        row = conn.execute("SELECT id, name FROM Department WHERE id = ?", (requested_department_id,)).fetchone()
        if row is None:
            raise ValueError(f"Department not found: {requested_department_id}")
        return {"departmentId": row["id"], "departmentName": row["name"]}

    row = conn.execute(
        "SELECT id, name FROM Department WHERE active = 1 ORDER BY name ASC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No active department found")
    return {"departmentId": row["id"], "departmentName": row["name"]}


def list_departments_for_admin(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name FROM Department WHERE active = 1 ORDER BY name ASC").fetchall()
    return [dict(r) for r in rows]
