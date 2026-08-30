"""
Comprehensive audit trail, written to its own SQLite file (config.py's
AUDIT_DB_PATH) separate from the app's regular database -- see
tools/migrate_audit_db.py. Distinct from app/services/audit.py, which is
a narrow, deliberately-unexpanded 6-action log kept for parity with the
original Next.js app; this one is the real "who did what, when" trail
covering every mutating request, hooked in globally (app/__init__.py's
after_request) rather than instrumented route-by-route, so it can't
silently miss a new route later.

Opens and closes its own connection per write rather than holding one
open across the request -- audit writes are infrequent enough (one per
mutating request) that the per-call overhead is irrelevant, and it keeps
this module fully independent of the main request's g.conn/transaction.
"""
from __future__ import annotations

import json
import sqlite3

from app.dates import now_db
from app.db import new_id

# Form field names never written to the log, matched case-insensitively as
# a substring -- covers password/token fields regardless of exact naming
# across current and future forms.
_SENSITIVE_FIELD_MARKERS = ("password", "csrf", "secret", "token")


def _sanitize_form(form: dict) -> dict:
    return {
        k: v for k, v in form.items()
        if not any(marker in k.lower() for marker in _SENSITIVE_FIELD_MARKERS)
    }


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def write_event(
    db_path: str, *, user: dict | None, method: str, path: str, endpoint: str | None,
    status_code: int, form: dict | None, view_args: dict | None, ip: str | None,
    entity: str | None = None, entity_id: str | None = None,
) -> None:
    detail = {}
    if form:
        sanitized = _sanitize_form(form)
        if sanitized:
            detail["form"] = sanitized
    if view_args:
        detail["viewArgs"] = view_args
    detail["path"] = path

    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO AuditEvent (id, at, userId, userName, userRole, branchId, action, "
            "entity, entityId, method, statusCode, detail, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id(), now_db(),
                user["id"] if user else None,
                user["name"] if user else None,
                user["role"] if user else None,
                user.get("branchId") if user else None,
                endpoint or path,
                entity, entity_id, method, status_code,
                json.dumps(detail) if detail else None,
                ip,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def query_events(
    db_path: str, *, user_id: str | None = None, role: str | None = None,
    action: str | None = None, date_from: str | None = None, date_to: str | None = None,
    limit: int = 200,
) -> list[dict]:
    conn = get_connection(db_path)
    try:
        conditions = []
        params: list = []
        if user_id:
            conditions.append("userId = ?"); params.append(user_id)
        if role:
            conditions.append("userRole = ?"); params.append(role)
        if action:
            conditions.append("action LIKE ?"); params.append(f"%{action}%")
        if date_from:
            conditions.append("at >= ?"); params.append(date_from)
        if date_to:
            conditions.append("at <= ?"); params.append(date_to)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM AuditEvent {where} ORDER BY at DESC LIMIT ?", params + [limit]
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def distinct_users(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT userId, userName FROM AuditEvent WHERE userId IS NOT NULL ORDER BY userName"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
