"""
One-time migration: adds gstNumber and billNo to Purchase, captured
alongside the existing supplier field on both the manual Purchase Entry
form and the Bulk Upload review screen -- needed so a future Zoho Books
webhook sync has a vendor GST and bill/invoice number to match against,
not just a free-text supplier name. The existing `date` field is reused
as the vendor's bill date (no separate column) since a purchase has
always been recorded against its invoice date in this app.

Safe to re-run (guards every ALTER TABLE).

Usage:
    .venv/bin/python tools/migrate_purchase_vendor_fields.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(Purchase)")}
    if "gstNumber" not in cols:
        conn.execute("ALTER TABLE Purchase ADD COLUMN gstNumber TEXT")
    if "billNo" not in cols:
        conn.execute("ALTER TABLE Purchase ADD COLUMN billNo TEXT")
    conn.commit()

    cols_after = {row[1] for row in conn.execute("PRAGMA table_info(Purchase)")}
    conn.close()
    ok = {"gstNumber", "billNo"} <= cols_after
    print(f"Migrated {db_path} -- Purchase.gstNumber/billNo present: {ok}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
