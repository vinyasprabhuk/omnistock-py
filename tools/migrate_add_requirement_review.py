"""
One-time migration: adds reject-with-comment support to KitchenRequirement.
Approve already existed via confirmedAt/confirmedById -- this adds the
reject half of the same review action (rejectedAt/rejectedById) plus a
shared comment field for whichever action was taken. Safe to re-run.

Usage:
    .venv/bin/python tools/migrate_add_requirement_review.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

NEW_COLUMNS = {
    "rejectedAt": "TEXT",
    "rejectedById": "TEXT",
    "reviewComment": "TEXT",
}


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(KitchenRequirement)")}
    for name, col_type in NEW_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE KitchenRequirement ADD COLUMN {name} {col_type}")
    conn.commit()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(KitchenRequirement)")}
    conn.close()
    print(f"Migrated {db_path} -- KitchenRequirement columns: {sorted(columns)}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
