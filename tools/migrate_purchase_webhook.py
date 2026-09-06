"""
One-time migration: adds the incoming-invoice webhook queue --
PurchaseWebhookEvent (one per received webhook call) and
PurchaseWebhookItem (its line items, auto-matched against Item Master).
An event sits PENDING until an admin reviews and either approves it
(creating a real Purchase via the existing create_purchase, capturing
gstNumber/billNo) or rejects it with a reason -- nothing from the
webhook ever touches Purchase/PurchaseItem directly.

Safe to re-run (CREATE TABLE IF NOT EXISTS).

Usage:
    .venv/bin/python tools/migrate_purchase_webhook.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS PurchaseWebhookEvent (
    id TEXT PRIMARY KEY,
    receivedAt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    sourceEvent TEXT,
    rawPayload TEXT NOT NULL,
    invoiceNumber TEXT,
    invoiceDate TEXT,
    vendorName TEXT,
    vendorGstin TEXT,
    totalAmount REAL,
    branchId TEXT REFERENCES Branch(id),
    reviewedById TEXT REFERENCES User(id),
    reviewedAt TEXT,
    rejectReason TEXT,
    resultingPurchaseId TEXT REFERENCES Purchase(id)
);
CREATE INDEX IF NOT EXISTS PurchaseWebhookEvent_status_idx
    ON PurchaseWebhookEvent(status);

CREATE TABLE IF NOT EXISTS PurchaseWebhookItem (
    id TEXT PRIMARY KEY,
    eventId TEXT NOT NULL REFERENCES PurchaseWebhookEvent(id) ON DELETE CASCADE,
    rawDescription TEXT,
    normalizedName TEXT,
    matchedItemId TEXT REFERENCES Item(id),
    confidence INTEGER,
    qty REAL,
    unit TEXT,
    rate REAL,
    taxAmount REAL,
    itemTotal REAL
);
CREATE INDEX IF NOT EXISTS PurchaseWebhookItem_event_idx
    ON PurchaseWebhookItem(eventId);
"""


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('PurchaseWebhookEvent', 'PurchaseWebhookItem')"
    )}
    conn.close()
    ok = tables == {"PurchaseWebhookEvent", "PurchaseWebhookItem"}
    print(f"Migrated {db_path} -- purchase webhook tables present: {ok}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
