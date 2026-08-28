"""
Audit log writes. The live app writes exactly 6 action types (not extended
to plain admin CRUD, despite a schema comment suggesting otherwise) --
replicate that scope exactly, not "complete" it.
"""
from __future__ import annotations

import json
import sqlite3

from app.dates import now_db
from app.db import new_id


def write(conn: sqlite3.Connection, user_id: str, branch_id: str | None, action: str,
          entity: str, entity_id: str, new_value: object = None) -> None:
    conn.execute(
        "INSERT INTO AuditLog (id, userId, branchId, action, entity, entityId, newValue, at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), user_id, branch_id, action, entity, entity_id,
         json.dumps(new_value) if new_value is not None else None, now_db()),
    )
