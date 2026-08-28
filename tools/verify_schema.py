"""
Asserts the working database (instance/dev.db) has exactly the table/column/index
shape and the exact date-string format the Python app is built against.

Run this any time a fresh copy of the live dev.db is dropped in, and again after
migrations, to catch schema drift before it becomes a silent business-logic bug.

Usage: python3 tools/verify_schema.py [path-to-db]
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "instance" / "dev.db"

# table -> set of expected column names (not exhaustive on types, since SQLite's
# own type affinity is loose; this catches renames/drops/additions, which is what
# actually breaks hand-written SQL).
EXPECTED_TABLES = {
    "AppSettings": {"id", "appName", "tagline", "logoPath", "headerColor", "accentColor",
                     "themeColor", "themeMode", "brandSize", "updatedAt"},
    "Branch": {"id", "name", "active", "createdAt", "updatedAt"},
    "User": {"id", "name", "email", "passwordHash", "role", "branchId", "active",
              "createdAt", "updatedAt"},
    "Item": {"id", "name", "unit", "purchasePrice", "category", "reorderLevel",
             "active", "createdAt", "updatedAt"},
    "ItemOpeningStock": {"id", "itemId", "branchId", "qty", "updatedAt"},
    "ItemAlias": {"id", "itemId", "alias", "createdAt"},
    "Department": {"id", "name", "active"},
    "Upload": {"id", "filePath", "fileHash", "uploadedById", "branchId", "createdAt"},
    "KitchenRequirement": {"id", "uploadId", "branchId", "date", "confirmedById",
                            "confirmedAt", "createdAt"},
    "KitchenRequirementItem": {"id", "requirementId", "departmentId", "extractedText",
                                "matchedItemId", "qty", "unit", "confidence", "status",
                                "createdAt"},
    "Purchase": {"id", "date", "branchId", "supplier", "receiptPath",
                 "receiptMimeType", "createdAt"},
    "PurchaseItem": {"id", "purchaseId", "itemId", "qty", "rate"},
    "StockIssue": {"id", "date", "branchId", "departmentId", "createdAt"},
    "StockIssueItem": {"id", "stockIssueId", "itemId", "qty"},
    "Wastage": {"id", "date", "branchId", "mealPeriod", "description", "weight",
                "unit", "pieces", "photoPath", "photoMimeType", "createdById",
                "createdAt"},
    "ProductionLog": {"id", "date", "branchId", "mealPeriod", "description", "weight",
                       "unit", "pieces", "photoPath", "photoMimeType", "createdById",
                       "createdAt"},
    "WastageMenuItem": {"id", "mealPeriod", "name", "isPieceCounted", "sortOrder",
                         "active", "createdAt"},
    "AuditLog": {"id", "userId", "branchId", "action", "entity", "entityId", "itemId",
                 "oldValue", "newValue", "at"},
}

# DATETIME columns that must hold the exact 29-char "YYYY-MM-DDTHH:MM:SS.mmm+00:00"
# format the live app writes. Business "date" columns are additionally checked for
# being UTC-midnight (T00:00:00.000+00:00) since that's the invariant calculations.py
# depends on for date-equality/range lookups.
DATETIME_COLUMNS = {
    "Branch": ["createdAt", "updatedAt"],
    "User": ["createdAt", "updatedAt"],
    "Item": ["createdAt", "updatedAt"],
    "ItemOpeningStock": ["updatedAt"],
    "ItemAlias": ["createdAt"],
    "Upload": ["createdAt"],
    "KitchenRequirement": ["confirmedAt", "createdAt"],  # confirmedAt nullable
    "KitchenRequirementItem": ["createdAt"],
    "Purchase": ["createdAt"],
    "StockIssue": ["createdAt"],
    "Wastage": ["createdAt"],
    "ProductionLog": ["createdAt"],
    "WastageMenuItem": ["createdAt"],
    "AuditLog": ["at"],
    "AppSettings": ["updatedAt"],
}
MIDNIGHT_DATE_COLUMNS = {
    "KitchenRequirement": ["date"],
    "Purchase": ["date"],
    "StockIssue": ["date"],
    "Wastage": ["date"],
    "ProductionLog": ["date"],
}

DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")
MIDNIGHT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00\.000\+00:00$")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    global had_failure
    had_failure = True


had_failure = False


def check_tables(conn: sqlite3.Connection) -> None:
    actual_tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing = set(EXPECTED_TABLES) - actual_tables
    if missing:
        fail(f"missing tables: {sorted(missing)}")
    extra = actual_tables - set(EXPECTED_TABLES) - {"_prisma_migrations"}
    if extra:
        print(f"NOTE: unexpected extra tables present (not necessarily a problem): {sorted(extra)}")

    for table, expected_cols in EXPECTED_TABLES.items():
        if table not in actual_tables:
            continue
        actual_cols = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        missing_cols = expected_cols - actual_cols
        extra_cols = actual_cols - expected_cols
        if missing_cols:
            fail(f"{table}: missing columns {sorted(missing_cols)}")
        if extra_cols:
            fail(f"{table}: unexpected columns {sorted(extra_cols)}")


def check_date_formats(conn: sqlite3.Connection) -> None:
    for table, cols in DATETIME_COLUMNS.items():
        for col in cols:
            rows = conn.execute(
                f'SELECT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL'
            ).fetchall()
            bad = [r[0] for r in rows if not DATETIME_RE.match(str(r[0]))]
            if bad:
                fail(f'{table}.{col}: {len(bad)} row(s) not in "YYYY-MM-DDTHH:MM:SS.mmm+00:00" '
                     f"format, e.g. {bad[0]!r}")

    for table, cols in MIDNIGHT_DATE_COLUMNS.items():
        for col in cols:
            rows = conn.execute(
                f'SELECT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL'
            ).fetchall()
            bad = [r[0] for r in rows if not MIDNIGHT_RE.match(str(r[0]))]
            if bad:
                fail(f"{table}.{col}: {len(bad)} row(s) not UTC-midnight, e.g. {bad[0]!r}")


def check_numeric_storage(conn: sqlite3.Connection) -> None:
    """
    Confirms qty/rate/price columns are stored as native REAL/INTEGER (not TEXT),
    which is what lets the Python port safely use `float` instead of `Decimal` to
    match the live app's Number()-based float64 arithmetic.
    """
    checks = [
        ("PurchaseItem", "qty"), ("PurchaseItem", "rate"),
        ("StockIssueItem", "qty"),
        ("Item", "purchasePrice"),
        ("ItemOpeningStock", "qty"),
    ]
    for table, col in checks:
        types = {
            row[0] for row in conn.execute(f'SELECT DISTINCT typeof("{col}") FROM "{table}"')
        }
        bad = types - {"integer", "real"}
        if bad:
            fail(f"{table}.{col}: expected numeric storage (integer/real), found {bad}")


def check_unique_constraints(conn: sqlite3.Connection) -> None:
    expected_unique = {
        "Branch": [("name",)],
        "User": [("email",)],
        "Item": [("name",)],
        "ItemOpeningStock": [("itemId", "branchId")],
        "ItemAlias": [("alias",)],
        "Department": [("name",)],
        "WastageMenuItem": [("mealPeriod", "name")],
    }
    for table, uniques in expected_unique.items():
        indexes = conn.execute(f'PRAGMA index_list("{table}")').fetchall()
        unique_col_sets = []
        for idx in indexes:
            idx_name = idx[1]
            is_unique = idx[2]
            if not is_unique:
                continue
            cols = tuple(
                r[2] for r in conn.execute(f'PRAGMA index_info("{idx_name}")')
            )
            unique_col_sets.append(cols)
        for expected in uniques:
            if expected not in unique_col_sets and tuple(sorted(expected)) not in [
                tuple(sorted(u)) for u in unique_col_sets
            ]:
                fail(f"{table}: expected unique constraint on {expected}, "
                     f"found unique sets {unique_col_sets}")


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    if not db_path.exists():
        print(f"FAIL: database not found at {db_path}")
        return 1

    print(f"Verifying schema of {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        check_tables(conn)
        check_date_formats(conn)
        check_numeric_storage(conn)
        check_unique_constraints(conn)
    finally:
        conn.close()

    if had_failure:
        print("\nSchema verification FAILED — see FAIL lines above.")
        return 1
    print("\nSchema verification PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
