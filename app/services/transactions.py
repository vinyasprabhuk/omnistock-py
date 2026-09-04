"""
Port of src/lib/actions/transactions.ts. Each write wraps its line items in
one transaction (all-or-nothing), then writes a single audit-log row.
"""
from __future__ import annotations

import sqlite3

from app.dates import date_key_to_db, now_db
from app.db import new_id
from app.services import audit
from app.services import storage
from app.services.departments import find_or_create_department


def create_purchase(conn: sqlite3.Connection, user_id: str, branch_id: str, date_key: str,
                     supplier: str | None, lines: list[dict]) -> str:
    """lines: [{"itemId": str, "qty": float, "rate": float}, ...]"""
    if not lines:
        raise ValueError("Add at least one line item")

    purchase_id = new_id()
    conn.execute(
        "INSERT INTO Purchase (id, date, branchId, supplier, createdAt) VALUES (?, ?, ?, ?, ?)",
        (purchase_id, date_key_to_db(date_key), branch_id, supplier or None, now_db()),
    )
    for line in lines:
        conn.execute(
            "INSERT INTO PurchaseItem (id, purchaseId, itemId, qty, rate) VALUES (?, ?, ?, ?, ?)",
            (new_id(), purchase_id, line["itemId"], line["qty"], line["rate"]),
        )
    audit.write(conn, user_id, branch_id, "PURCHASE_ADDED", "Purchase", purchase_id, lines)
    conn.commit()
    return purchase_id


def attach_purchase_receipt(conn: sqlite3.Connection, purchase_id: str,
                             file_bytes: bytes, filename: str, mime_type: str | None) -> None:
    if not file_bytes:
        return
    saved = storage.save(file_bytes, filename)
    conn.execute(
        "UPDATE Purchase SET receiptPath = ?, receiptMimeType = ? WHERE id = ?",
        (saved["filePath"], mime_type or "application/octet-stream", purchase_id),
    )
    conn.commit()


def create_stock_issue(conn: sqlite3.Connection, user_id: str, branch_id: str, date_key: str,
                        department_name: str, lines: list[dict],
                        source_requirement_id: str | None = None) -> str:
    """lines: [{"itemId": str, "qty": float}, ...]

    source_requirement_id links this issue back to the KitchenRequirement
    that produced it (see issue_kitchen_requirement) -- None for every
    other caller (manual Stock Issue entry, Excel import)."""
    if not lines:
        raise ValueError("Add at least one line item")

    department = find_or_create_department(conn, department_name)

    issue_id = new_id()
    conn.execute(
        "INSERT INTO StockIssue (id, date, branchId, departmentId, createdAt, sourceRequirementId) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (issue_id, date_key_to_db(date_key), branch_id, department["id"], now_db(), source_requirement_id),
    )
    for line in lines:
        conn.execute(
            "INSERT INTO StockIssueItem (id, stockIssueId, itemId, qty) VALUES (?, ?, ?, ?)",
            (new_id(), issue_id, line["itemId"], line["qty"]),
        )
    audit.write(conn, user_id, branch_id, "STOCK_ISSUED", "StockIssue", issue_id, lines)
    conn.commit()
    return issue_id
