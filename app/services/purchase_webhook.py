"""
Incoming-invoice webhook queue. A local middleware (e.g. an OCR/Zoho
integration) POSTs a parsed vendor invoice here; every event is stored
PENDING and auto-matched against Item Master, but nothing ever touches
Purchase/PurchaseItem until an admin reviews and explicitly approves it
on the Incoming Invoices screen -- see app/views/webhooks.py for the
endpoint itself and its localhost-only guard.

Expected payload shape (from the real InvoiceToZoho-Inventory sender):
{
  "event": "invoice.pushed_to_inventory",
  "invoice": {
    "invoice_number": "43592", "invoice_date": "2026-08-23",
    "vendor": {"name": "...", "gstin": "..."},
    "financials": {"total_amount": 972, ...},
    "items": [
      {"raw_description": "...", "normalized_name": "...",
       "invoice_quantity": 10, "invoice_unit": "Kg", "invoice_rate": 72,
       "tax_amount": 0, "item_total": 720},
      ...
    ]
  }
}
Any of these fields being absent/differently-shaped doesn't crash
ingestion -- only invoice.items needs at least one entry, everything
else is stored as-is (including None) for the reviewer to fill in.
"""
from __future__ import annotations

import json
import sqlite3

from app.dates import now_db
from app.db import new_id
from app.services import audit
from app.services.match_item import match_item
from app.services.transactions import create_purchase


def _default_branch_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT id FROM Branch WHERE active = 1 ORDER BY createdAt ASC LIMIT 1").fetchone()
    return row["id"] if row else None


def ingest_purchase_invoice_webhook(conn: sqlite3.Connection, payload: dict) -> str:
    """Stores the incoming payload as a PENDING PurchaseWebhookEvent +
    its line items, auto-matching each item's normalized_name (falling
    back to raw_description) against Item Master via the same
    match_item used by the Excel-upload flows. Returns the new event id.
    Raises ValueError on a payload with no usable invoice.items."""
    invoice = payload.get("invoice") or {}
    items = invoice.get("items") or []
    if not items:
        raise ValueError("Payload has no invoice.items to review")

    vendor = invoice.get("vendor") or {}
    financials = invoice.get("financials") or {}

    event_id = new_id()
    conn.execute(
        "INSERT INTO PurchaseWebhookEvent "
        "(id, receivedAt, status, sourceEvent, rawPayload, invoiceNumber, invoiceDate, "
        "vendorName, vendorGstin, totalAmount, branchId) "
        "VALUES (?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, now_db(), payload.get("event"), json.dumps(payload),
         invoice.get("invoice_number"), invoice.get("invoice_date"),
         vendor.get("name"), vendor.get("gstin"), financials.get("total_amount"),
         _default_branch_id(conn)),
    )

    for item in items:
        normalized_name = item.get("normalized_name") or ""
        raw_description = item.get("raw_description") or ""
        match = match_item(conn, normalized_name or raw_description)
        conn.execute(
            "INSERT INTO PurchaseWebhookItem "
            "(id, eventId, rawDescription, normalizedName, matchedItemId, confidence, "
            "qty, unit, rate, taxAmount, itemTotal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), event_id, raw_description, normalized_name,
             match["matchedItemId"], match["confidence"],
             item.get("invoice_quantity"), item.get("invoice_unit"), item.get("invoice_rate"),
             item.get("tax_amount"), item.get("item_total")),
        )
    conn.commit()
    return event_id


def get_pending_webhook_events(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT e.id AS id, e.receivedAt AS receivedAt, e.invoiceNumber AS invoiceNumber, "
        "e.invoiceDate AS invoiceDate, e.vendorName AS vendorName, e.vendorGstin AS vendorGstin, "
        "e.totalAmount AS totalAmount, COUNT(i.id) AS itemCount, "
        "SUM(CASE WHEN i.matchedItemId IS NULL THEN 1 ELSE 0 END) AS unmatchedCount "
        "FROM PurchaseWebhookEvent e LEFT JOIN PurchaseWebhookItem i ON i.eventId = e.id "
        "WHERE e.status = 'PENDING' GROUP BY e.id ORDER BY e.receivedAt DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_webhook_event_for_review(conn: sqlite3.Connection, event_id: str) -> dict | None:
    event = conn.execute("SELECT * FROM PurchaseWebhookEvent WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        return None
    items = conn.execute(
        "SELECT i.*, it.name AS matchedItemName, it.unit AS matchedItemUnit "
        "FROM PurchaseWebhookItem i LEFT JOIN Item it ON it.id = i.matchedItemId "
        "WHERE i.eventId = ? ORDER BY i.rowid ASC",
        (event_id,),
    ).fetchall()
    result = dict(event)
    result["items"] = [dict(r) for r in items]
    return result


def approve_webhook_event(conn: sqlite3.Connection, user_id: str, event_id: str,
                           branch_id: str, lines: list[dict]) -> str:
    """lines: [{"itemId": str, "qty": float, "rate": float}, ...] --
    reviewer-confirmed/corrected values, not necessarily identical to
    what was auto-matched. Creates the real Purchase (capturing
    vendorGstin/invoiceNumber as gstNumber/billNo) and links it back."""
    event = conn.execute("SELECT * FROM PurchaseWebhookEvent WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise ValueError("Event not found")
    if event["status"] != "PENDING":
        raise ValueError("This event has already been reviewed")
    if not lines:
        raise ValueError("Add at least one line item with a matched item and quantity")
    if not event["invoiceDate"]:
        raise ValueError("This invoice has no date -- cannot create a Purchase without one")

    purchase_id = create_purchase(
        conn, user_id, branch_id, event["invoiceDate"], event["vendorName"], lines,
        gst_number=event["vendorGstin"], bill_no=event["invoiceNumber"],
    )
    conn.execute(
        "UPDATE PurchaseWebhookEvent SET status = 'APPROVED', reviewedById = ?, reviewedAt = ?, "
        "resultingPurchaseId = ? WHERE id = ?",
        (user_id, now_db(), purchase_id, event_id),
    )
    audit.write(conn, user_id, branch_id, "PURCHASE_ADDED", "Purchase", purchase_id,
                {"source": "webhook", "webhookEventId": event_id})
    conn.commit()
    return purchase_id


def reject_webhook_event(conn: sqlite3.Connection, user_id: str, event_id: str, reason: str) -> None:
    if not reason or not reason.strip():
        raise ValueError("A reason is required when rejecting")
    event = conn.execute("SELECT status FROM PurchaseWebhookEvent WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise ValueError("Event not found")
    if event["status"] != "PENDING":
        raise ValueError("This event has already been reviewed")
    conn.execute(
        "UPDATE PurchaseWebhookEvent SET status = 'REJECTED', reviewedById = ?, reviewedAt = ?, "
        "rejectReason = ? WHERE id = ?",
        (user_id, now_db(), reason.strip(), event_id),
    )
    conn.commit()
