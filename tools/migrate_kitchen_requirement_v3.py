"""
One-time migration: adds KitchenRequirement.submittedAt, splitting "Save"
(writes a department's items to the server immediately, so progress
survives a crash) from "Submit" (the point Admin/Manager can actually see
and act on the request). Before this, every Save-created draft was
already visible in the admin Pending Review list the moment the first
department was saved, even if kitchen was still mid-way through adding
more departments.

Safe to re-run (guards the ALTER TABLE). Existing rows predate the
draft concept entirely -- backfilled to already-submitted (via
confirmedAt/createdAt) so nothing already in front of an admin
disappears.

Usage:
    .venv/bin/python tools/migrate_kitchen_requirement_v3.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    kr_cols = {row[1] for row in conn.execute("PRAGMA table_info(KitchenRequirement)")}
    added = "submittedAt" not in kr_cols
    if added:
        conn.execute("ALTER TABLE KitchenRequirement ADD COLUMN submittedAt TEXT")
        conn.execute(
            "UPDATE KitchenRequirement SET submittedAt = COALESCE(confirmedAt, createdAt) "
            "WHERE submittedAt IS NULL"
        )
    conn.commit()

    kr_cols_after = {row[1] for row in conn.execute("PRAGMA table_info(KitchenRequirement)")}
    conn.close()
    print(f"Migrated {db_path} -- KitchenRequirement.submittedAt present: {'submittedAt' in kr_cols_after}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
