"""
Ports of purchaseExcel.ts / stockIssueExcel.ts / openingStockExcel.ts --
the preview -> commit two-step bulk-upload flows. All three reuse the same
parsing/matching pipeline as Kitchen Requirement, for consistency.
"""
from __future__ import annotations

import sqlite3

from app.dates import date_key_to_db, now_db
from app.db import new_id
from app.parsing.kitchen_excel import parse_kitchen_excel
from app.parsing.kitchen_word import parse_kitchen_word
from app.parsing.opening_stock_excel import parse_opening_stock_excel
from app.services import audit
from app.services.departments import find_or_create_department
from app.services.match_item import match_item
from app.services.normalize_unit import normalize_unit


def _extraction_for_file(file_bytes: bytes, filename: str) -> dict:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("docx", "doc"):
        return parse_kitchen_word(file_bytes)
    return parse_kitchen_excel(file_bytes)


# --- Purchases ---

def preview_purchase_excel(conn: sqlite3.Connection, file_bytes: bytes, filename: str) -> list[dict]:
    extraction = _extraction_for_file(file_bytes, filename)
    rows = []
    for dept in extraction["departments"]:
        for item in dept["items"]:
            normalized = normalize_unit(item["quantity"], item["unit"])
            match = match_item(conn, item["raw_item"])
            matched_price = 0.0
            if match["matchedItemId"]:
                price_row = conn.execute(
                    "SELECT purchasePrice FROM Item WHERE id = ?", (match["matchedItemId"],)
                ).fetchone()
                if price_row:
                    matched_price = float(price_row["purchasePrice"])
            rows.append({
                "extractedText": item["raw_item"],
                "matchedItemId": match["matchedItemId"],
                "matchedItemName": match["matchedItemName"],
                "qty": normalized["qty"],
                "unit": normalized["unit"] or "UNKNOWN",
                "rate": matched_price,
                "confidence": match["confidence"],
            })
    return rows


def commit_purchase_excel(conn: sqlite3.Connection, user_id: str, branch_id: str, date_key: str,
                           supplier: str | None, rows: list[dict]) -> dict:
    """rows: [{"itemId": str, "qty": float, "rate": float}, ...]"""
    if not rows:
        raise ValueError("No rows to save")

    purchase_id = new_id()
    conn.execute(
        "INSERT INTO Purchase (id, date, branchId, supplier, createdAt) VALUES (?, ?, ?, ?, ?)",
        (purchase_id, date_key_to_db(date_key), branch_id, supplier or None, now_db()),
    )
    for r in rows:
        conn.execute(
            "INSERT INTO PurchaseItem (id, purchaseId, itemId, qty, rate) VALUES (?, ?, ?, ?, ?)",
            (new_id(), purchase_id, r["itemId"], r["qty"], r["rate"]),
        )
    audit.write(conn, user_id, branch_id, "PURCHASE_ADDED", "Purchase", purchase_id,
                {"source": "excel-import", "rows": len(rows)})
    conn.commit()
    return {"itemsCreated": len(rows)}


# --- Stock Issue ---

def preview_stock_issue_excel(conn: sqlite3.Connection, file_bytes: bytes, filename: str) -> list[dict]:
    extraction = _extraction_for_file(file_bytes, filename)
    rows = []
    for dept in extraction["departments"]:
        for item in dept["items"]:
            normalized = normalize_unit(item["quantity"], item["unit"])
            match = match_item(conn, item["raw_item"])
            rows.append({
                "departmentName": dept["name"],
                "extractedText": item["raw_item"],
                "matchedItemId": match["matchedItemId"],
                "matchedItemName": match["matchedItemName"],
                "qty": normalized["qty"],
                "unit": normalized["unit"] or "UNKNOWN",
                "confidence": match["confidence"],
            })
    return rows


def commit_stock_issue_excel(conn: sqlite3.Connection, user_id: str, branch_id: str, date_key: str,
                              rows: list[dict]) -> dict:
    """rows: [{"departmentName": str, "itemId": str, "qty": float}, ...]"""
    by_department: dict[str, list[dict]] = {}
    for r in rows:
        by_department.setdefault(r["departmentName"], []).append({"itemId": r["itemId"], "qty": r["qty"]})

    for department_name, items in by_department.items():
        department = find_or_create_department(conn, department_name)
        issue_id = new_id()
        conn.execute(
            "INSERT INTO StockIssue (id, date, branchId, departmentId, createdAt) VALUES (?, ?, ?, ?, ?)",
            (issue_id, date_key_to_db(date_key), branch_id, department["id"], now_db()),
        )
        for item in items:
            conn.execute(
                "INSERT INTO StockIssueItem (id, stockIssueId, itemId, qty) VALUES (?, ?, ?, ?)",
                (new_id(), issue_id, item["itemId"], item["qty"]),
            )

    import time
    audit.write(conn, user_id, branch_id, "STOCK_ISSUED", "StockIssue", f"excel-import-{int(time.time() * 1000)}",
                {"departments": len(by_department), "rows": len(rows)})
    conn.commit()
    return {"departmentsCreated": len(by_department), "itemsCreated": len(rows)}


# --- Opening Stock ---

def preview_opening_stock_excel(conn: sqlite3.Connection, file_bytes: bytes) -> list[dict]:
    parsed = parse_opening_stock_excel(file_bytes)
    rows = []
    for p in parsed:
        match = match_item(conn, p["itemText"])
        rows.append({
            "extractedText": p["itemText"],
            "matchedItemId": match["matchedItemId"],
            "matchedItemName": match["matchedItemName"],
            "qty": p["qty"],
            "confidence": match["confidence"],
        })
    return rows


def commit_opening_stock_excel(conn: sqlite3.Connection, branch_id: str, rows: list[dict]) -> dict:
    """rows: [{"itemId": str, "qty": float}, ...]"""
    for r in rows:
        existing = conn.execute(
            "SELECT id FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (r["itemId"], branch_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE ItemOpeningStock SET qty = ?, updatedAt = ? WHERE id = ?",
                (r["qty"], now_db(), existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO ItemOpeningStock (id, itemId, branchId, qty, updatedAt) VALUES (?, ?, ?, ?, ?)",
                (new_id(), r["itemId"], branch_id, r["qty"], now_db()),
            )
    conn.commit()
    return {"updated": len(rows)}
