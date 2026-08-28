"""
Port of src/lib/auth/pageBranch.ts.

Page-rendering variant of resolve_branch_scope: ADMIN gets a sensible
default (first active branch) instead of a hard error when no branch is
chosen yet, since a page load shouldn't fail just because the admin hasn't
picked one. Mutating actions still use the strict resolve_branch_scope.
"""
from __future__ import annotations

import sqlite3


def page_resolve_branch(conn: sqlite3.Connection, user: dict,
                         requested_branch_id: str | None = None) -> dict:
    role = user["role"]
    branch_id = user.get("branchId")

    if role != "ADMIN":
        if not branch_id:
            raise ValueError("User has no assigned branch")
        row = conn.execute("SELECT id, name FROM Branch WHERE id = ?", (branch_id,)).fetchone()
        if row is None:
            raise ValueError(f"Branch not found: {branch_id}")
        return {"branchId": row["id"], "branchName": row["name"]}

    if requested_branch_id:
        row = conn.execute("SELECT id, name FROM Branch WHERE id = ?", (requested_branch_id,)).fetchone()
        if row is None:
            raise ValueError(f"Branch not found: {requested_branch_id}")
        return {"branchId": row["id"], "branchName": row["name"]}

    row = conn.execute(
        "SELECT id, name FROM Branch WHERE active = 1 ORDER BY createdAt ASC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No active branch found")
    return {"branchId": row["id"], "branchName": row["name"]}


def list_branches_for_admin(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name FROM Branch WHERE active = 1 ORDER BY name ASC").fetchall()
    return [dict(r) for r in rows]
