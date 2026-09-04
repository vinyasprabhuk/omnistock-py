"""
One-time migration: adds the 3-stage Kitchen Requirement lifecycle
(PENDING -> APPROVED -> ISSUED, replacing the old fused
confirm-also-issues behavior), Regular/Extra request typing, a link from
StockIssue back to the KitchenRequirement that produced it, and the
mandatory-reason edit-after-approval tables. Safe to re-run (guards every
ALTER TABLE, CREATE TABLE IF NOT EXISTS for new tables).

Usage:
    .venv/bin/python tools/migrate_kitchen_requirement_v2.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

NEW_TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS KitchenRequirementEdit (
    id TEXT PRIMARY KEY,
    requirementId TEXT NOT NULL REFERENCES KitchenRequirement(id) ON DELETE CASCADE,
    editedById TEXT NOT NULL REFERENCES User(id),
    reason TEXT NOT NULL,
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS KitchenRequirementEdit_requirement_idx
    ON KitchenRequirementEdit(requirementId);

CREATE TABLE IF NOT EXISTS KitchenRequirementItemChange (
    id TEXT PRIMARY KEY,
    editId TEXT NOT NULL REFERENCES KitchenRequirementEdit(id) ON DELETE CASCADE,
    requirementItemId TEXT REFERENCES KitchenRequirementItem(id) ON DELETE SET NULL,
    itemLabel TEXT NOT NULL,
    action TEXT NOT NULL,
    previousQty REAL,
    newQty REAL,
    reason TEXT NOT NULL,
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS KitchenRequirementItemChange_edit_idx
    ON KitchenRequirementItemChange(editId);
"""


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    kr_cols = {row[1] for row in conn.execute("PRAGMA table_info(KitchenRequirement)")}
    added_status = "status" not in kr_cols
    if added_status:
        conn.execute("ALTER TABLE KitchenRequirement ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'")
    if "requestType" not in kr_cols:
        conn.execute("ALTER TABLE KitchenRequirement ADD COLUMN requestType TEXT NOT NULL DEFAULT 'REGULAR'")
    if "issuedAt" not in kr_cols:
        conn.execute("ALTER TABLE KitchenRequirement ADD COLUMN issuedAt TEXT")
    if "issuedById" not in kr_cols:
        conn.execute("ALTER TABLE KitchenRequirement ADD COLUMN issuedById TEXT REFERENCES User(id)")

    if added_status:
        # Historically, "confirmed" always meant stock was already
        # auto-issued (the old fused flow) -- backfill to ISSUED, not
        # APPROVED, to match what actually happened rather than forcing a
        # re-Issue click on every pre-existing row.
        conn.execute("UPDATE KitchenRequirement SET status = 'ISSUED' WHERE confirmedAt IS NOT NULL")

    si_cols = {row[1] for row in conn.execute("PRAGMA table_info(StockIssue)")}
    if "sourceRequirementId" not in si_cols:
        conn.execute("ALTER TABLE StockIssue ADD COLUMN sourceRequirementId TEXT REFERENCES KitchenRequirement(id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS StockIssue_source_dept_uidx "
        "ON StockIssue(sourceRequirementId, departmentId) WHERE sourceRequirementId IS NOT NULL"
    )

    conn.executescript(NEW_TABLES_SCHEMA)
    conn.commit()

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('KitchenRequirementEdit', 'KitchenRequirementItemChange')"
    )}
    kr_cols_after = {row[1] for row in conn.execute("PRAGMA table_info(KitchenRequirement)")}
    si_cols_after = {row[1] for row in conn.execute("PRAGMA table_info(StockIssue)")}
    conn.close()
    kr_new_cols_ok = {"status", "requestType", "issuedAt", "issuedById"} <= kr_cols_after
    tables_ok = tables == {"KitchenRequirementEdit", "KitchenRequirementItemChange"}
    print(
        f"Migrated {db_path} -- KitchenRequirement new columns present: {kr_new_cols_ok}; "
        f"StockIssue.sourceRequirementId present: {'sourceRequirementId' in si_cols_after}; "
        f"new tables present: {tables_ok}"
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
