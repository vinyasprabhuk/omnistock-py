"""Port of src/lib/actions/excelImport.ts -- the legacy workbook two-step
preview/commit import. The original .xlsx is never modified; items are
upserted by name, day-sheet Purchase Qty/Usage Qty become normal Purchase/
StockIssue transactions dated to that sheet's date, attributed to a generic
"Excel Import" department (the old data had no per-department breakdown)."""
from __future__ import annotations

import sqlite3

from app.dates import now_db
from app.db import new_id
from app.parsing.import_workbook import ParsedWorkbook, parse_workbook
from app.services.departments import find_or_create_department


def preview_excel_import(file_bytes: bytes) -> ParsedWorkbook:
    return parse_workbook(file_bytes)


def commit_excel_import(conn: sqlite3.Connection, file_bytes: bytes, branch_id: str) -> dict:
    parsed = parse_workbook(file_bytes)

    item_id_by_row: dict[int, str] = {}
    for item in parsed["items"]:
        existing = conn.execute("SELECT id FROM Item WHERE name = ?", (item["name"],)).fetchone()
        if existing:
            item_id = existing["id"]
            conn.execute(
                "UPDATE Item SET unit = ?, purchasePrice = ?, updatedAt = ? WHERE id = ?",
                (item["unit"], item["purchasePrice"], now_db(), item_id),
            )
        else:
            item_id = new_id()
            conn.execute(
                "INSERT INTO Item (id, name, unit, purchasePrice, active, createdAt, updatedAt) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (item_id, item["name"], item["unit"], item["purchasePrice"], now_db(), now_db()),
            )
        item_id_by_row[item["row"]] = item_id

        os_existing = conn.execute(
            "SELECT id FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (item_id, branch_id)
        ).fetchone()
        if os_existing:
            conn.execute("UPDATE ItemOpeningStock SET qty = ?, updatedAt = ? WHERE id = ?",
                         (item["openingStock"], now_db(), os_existing["id"]))
        else:
            conn.execute(
                "INSERT INTO ItemOpeningStock (id, itemId, branchId, qty, updatedAt) VALUES (?, ?, ?, ?, ?)",
                (new_id(), item_id, branch_id, item["openingStock"], now_db()),
            )

    by_date: dict[str, list[dict]] = {}
    for t in parsed["dayTransactions"]:
        by_date.setdefault(t["date"], []).append(t)

    import_department = find_or_create_department(conn, "Excel Import")

    purchases_created = 0
    issues_created = 0

    for date_key, transactions in by_date.items():
        db_date = f"{date_key}T00:00:00.000+00:00"

        purchase_lines = [t for t in transactions if t["purchaseQty"] > 0 and t["row"] in item_id_by_row]
        if purchase_lines:
            purchase_id = new_id()
            conn.execute(
                "INSERT INTO Purchase (id, date, branchId, supplier, createdAt) VALUES (?, ?, ?, ?, ?)",
                (purchase_id, db_date, branch_id, "Excel import", now_db()),
            )
            for t in purchase_lines:
                conn.execute(
                    "INSERT INTO PurchaseItem (id, purchaseId, itemId, qty, rate) VALUES (?, ?, ?, ?, 0)",
                    (new_id(), purchase_id, item_id_by_row[t["row"]], t["purchaseQty"]),
                )
            purchases_created += 1

        usage_lines = [t for t in transactions if t["usageQty"] > 0 and t["row"] in item_id_by_row]
        if usage_lines:
            issue_id = new_id()
            conn.execute(
                "INSERT INTO StockIssue (id, date, branchId, departmentId, createdAt) VALUES (?, ?, ?, ?, ?)",
                (issue_id, db_date, branch_id, import_department["id"], now_db()),
            )
            for t in usage_lines:
                conn.execute(
                    "INSERT INTO StockIssueItem (id, stockIssueId, itemId, qty) VALUES (?, ?, ?, ?)",
                    (new_id(), issue_id, item_id_by_row[t["row"]], t["usageQty"]),
                )
            issues_created += 1

    conn.commit()
    return {"itemsCreated": len(parsed["items"]), "purchasesCreated": purchases_created, "issuesCreated": issues_created}
