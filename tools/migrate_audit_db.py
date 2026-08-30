"""
Creates the separate audit database (instance/audit.db by default, or
AUDIT_DB_PATH) -- deliberately its own SQLite file, not a table inside
dev.db, so the audit trail isn't editable in the same transaction as the
data it's auditing.

Usage:
    .venv/bin/python tools/migrate_audit_db.py [path-to-audit-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS AuditEvent (
    id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    userId TEXT,
    userName TEXT,
    userRole TEXT,
    branchId TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entityId TEXT,
    method TEXT NOT NULL,
    statusCode INTEGER,
    detail TEXT,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS AuditEvent_at_idx ON AuditEvent(at);
CREATE INDEX IF NOT EXISTS AuditEvent_userId_idx ON AuditEvent(userId);
CREATE INDEX IF NOT EXISTS AuditEvent_action_idx ON AuditEvent(action);
"""


def migrate(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    try:
        db_path.chmod(0o600)
    except OSError:
        pass
    print(f"Migrated {db_path} -- AuditEvent table ready.")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "audit.db"
    migrate(target)
