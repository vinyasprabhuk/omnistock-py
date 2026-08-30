"""
One-time migration: adds DEPARTMENT_LEAD support --  User.departmentId
column, and the WorkstationPhoto table department leads log their station
photos into. Safe to re-run (guards the ALTER TABLE, CREATE TABLE IF NOT
EXISTS for the new table).

Usage:
    .venv/bin/python tools/migrate_add_workstation.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

WORKSTATION_PHOTO_SCHEMA = """
CREATE TABLE IF NOT EXISTS WorkstationPhoto (
    id TEXT PRIMARY KEY,
    branchId TEXT NOT NULL REFERENCES Branch(id),
    departmentId TEXT NOT NULL REFERENCES Department(id),
    photoPath TEXT NOT NULL,
    photoMimeType TEXT NOT NULL,
    createdById TEXT NOT NULL REFERENCES User(id),
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS WorkstationPhoto_department_month_idx
    ON WorkstationPhoto(departmentId, createdAt);
"""


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(User)")}
    if "departmentId" not in existing_cols:
        conn.execute("ALTER TABLE User ADD COLUMN departmentId TEXT REFERENCES Department(id)")

    conn.executescript(WORKSTATION_PHOTO_SCHEMA)
    conn.commit()

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = 'WorkstationPhoto'"
    )]
    cols = {row[1] for row in conn.execute("PRAGMA table_info(User)")}
    conn.close()
    print(f"Migrated {db_path} -- WorkstationPhoto present: {bool(tables)}; User.departmentId present: {'departmentId' in cols}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
