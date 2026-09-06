"""e2e coverage for the incoming-invoice webhook queue: ingestion (with
its localhost-only guard), auto-matching against Item Master, and the
admin review screen's Approve (-> creates a real Purchase) / Reject
paths. Payload shape matches the real InvoiceToZoho-Inventory sender
captured via webhook.site during development.
"""
from __future__ import annotations

import json

from tests.conftest import csrf_token, login, make_user


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


def _payload(item_name="Aval", invoice_number="43592", invoice_date="2026-08-23"):
    return {
        "event": "invoice.pushed_to_inventory",
        "timestamp": "2026-09-06T16:23:55.968555Z",
        "organization": {"id": "org-1", "name": "Primary Restaurant", "gstin": None},
        "invoice": {
            "id": "inv-1",
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "status": "APPROVED",
            "currency": "INR",
            "total_amount": 972,
            "vendor": {"name": "NEW LAKSHMI STORES", "gstin": "33AATFN2000G1ZP"},
            "financials": {"subtotal": 960, "taxable_amount": 960, "cgst": 6, "sgst": 6,
                            "igst": 0, "tax_amount": 12, "round_off": 0, "total_amount": 972},
            "items": [
                {"s_no": 1, "raw_description": "AVUL NICE BULK", "normalized_name": item_name,
                 "hsn_sac": "19041020", "invoice_quantity": 10, "invoice_unit": "Kg",
                 "invoice_rate": 72, "taxable_amount": 720, "tax_rate": 0,
                 "tax_amount": 0, "item_total": 720},
            ],
        },
    }


class TestWebhookIngestion:
    def test_localhost_request_is_accepted(self, full_app, full_db_conn):
        client = full_app.test_client()
        resp = client.post("/webhooks/purchase-invoice", data=json.dumps(_payload()),
                            content_type="application/json")
        assert resp.status_code == 201
        event_id = resp.get_json()["eventId"]
        row = full_db_conn.execute(
            "SELECT status, vendorName, vendorGstin, invoiceNumber, invoiceDate FROM PurchaseWebhookEvent WHERE id = ?",
            (event_id,),
        ).fetchone()
        assert row["status"] == "PENDING"
        assert row["vendorName"] == "NEW LAKSHMI STORES"
        assert row["vendorGstin"] == "33AATFN2000G1ZP"
        assert row["invoiceNumber"] == "43592"
        assert row["invoiceDate"] == "2026-08-23"

    def test_non_localhost_request_is_rejected(self, full_app, full_db_conn):
        client = full_app.test_client()
        resp = client.post("/webhooks/purchase-invoice", data=json.dumps(_payload()),
                            content_type="application/json",
                            environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
        assert resp.status_code == 403
        assert full_db_conn.execute("SELECT COUNT(*) FROM PurchaseWebhookEvent").fetchone()[0] == 0

    def test_payload_with_no_items_is_rejected(self, full_app, full_db_conn):
        client = full_app.test_client()
        payload = _payload()
        payload["invoice"]["items"] = []
        resp = client.post("/webhooks/purchase-invoice", data=json.dumps(payload),
                            content_type="application/json")
        assert resp.status_code == 400

    def test_non_json_body_is_rejected(self, full_app, full_db_conn):
        client = full_app.test_client()
        resp = client.post("/webhooks/purchase-invoice", data="not json", content_type="text/plain")
        assert resp.status_code == 400

    def test_item_auto_matched_against_item_master(self, full_app, full_db_conn):
        client = full_app.test_client()
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE name = 'Aval' LIMIT 1").fetchone()
        assert item is not None, "fixture depends on 'Aval' existing in the pristine Item Master"

        resp = client.post("/webhooks/purchase-invoice", data=json.dumps(_payload(item_name="Aval")),
                            content_type="application/json")
        event_id = resp.get_json()["eventId"]
        row = full_db_conn.execute(
            "SELECT matchedItemId, confidence FROM PurchaseWebhookItem WHERE eventId = ?", (event_id,)
        ).fetchone()
        assert row["matchedItemId"] == item["id"]
        assert row["confidence"] >= 90


class TestIncomingInvoiceReview:
    def _ingest(self, client, **kw):
        resp = client.post("/webhooks/purchase-invoice", data=json.dumps(_payload(**kw)),
                            content_type="application/json")
        return resp.get_json()["eventId"]

    def test_pending_event_shown_on_incoming_list(self, full_app, full_db_conn, branch_id):
        webhook_client = full_app.test_client()
        self._ingest(webhook_client)

        admin = _admin_client(full_app, full_db_conn)
        resp = admin.get("/purchases/incoming")
        assert resp.status_code == 200
        assert b"NEW LAKSHMI STORES" in resp.data
        assert b"43592" in resp.data

    def test_approve_creates_purchase_with_gst_and_bill_no(self, full_app, full_db_conn, branch_id):
        webhook_client = full_app.test_client()
        item = full_db_conn.execute("SELECT id FROM Item WHERE name = 'Aval' LIMIT 1").fetchone()
        event_id = self._ingest(webhook_client, item_name="Aval")

        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        before = full_db_conn.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0]

        resp = admin.post(f"/purchases/incoming/{event_id}/approve", data={
            "_csrf_token": token, "branchId": branch_id,
            "itemId": item["id"], "qty": "10", "rate": "72",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"approved" in resp.data.lower()

        after = full_db_conn.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0]
        assert after == before + 1

        event_row = full_db_conn.execute(
            "SELECT status, resultingPurchaseId FROM PurchaseWebhookEvent WHERE id = ?", (event_id,)
        ).fetchone()
        assert event_row["status"] == "APPROVED"
        purchase = full_db_conn.execute(
            "SELECT supplier, gstNumber, billNo FROM Purchase WHERE id = ?", (event_row["resultingPurchaseId"],)
        ).fetchone()
        assert purchase["supplier"] == "NEW LAKSHMI STORES"
        assert purchase["gstNumber"] == "33AATFN2000G1ZP"
        assert purchase["billNo"] == "43592"

    def test_reject_requires_reason_and_marks_event_rejected(self, full_app, full_db_conn, branch_id):
        webhook_client = full_app.test_client()
        event_id = self._ingest(webhook_client)

        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)

        resp_no_reason = admin.post(f"/purchases/incoming/{event_id}/reject",
                                     data={"_csrf_token": token, "reason": ""}, follow_redirects=True)
        assert b"reason is required" in resp_no_reason.data
        status = full_db_conn.execute("SELECT status FROM PurchaseWebhookEvent WHERE id = ?", (event_id,)).fetchone()["status"]
        assert status == "PENDING"

        admin.post(f"/purchases/incoming/{event_id}/reject",
                   data={"_csrf_token": token, "reason": "Duplicate of an already-entered bill"})
        row = full_db_conn.execute(
            "SELECT status, rejectReason FROM PurchaseWebhookEvent WHERE id = ?", (event_id,)
        ).fetchone()
        assert row["status"] == "REJECTED"
        assert row["rejectReason"] == "Duplicate of an already-entered bill"

    def test_approving_already_reviewed_event_is_blocked(self, full_app, full_db_conn, branch_id):
        webhook_client = full_app.test_client()
        item = full_db_conn.execute("SELECT id FROM Item WHERE name = 'Aval' LIMIT 1").fetchone()
        event_id = self._ingest(webhook_client, item_name="Aval")

        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        admin.post(f"/purchases/incoming/{event_id}/reject",
                   data={"_csrf_token": token, "reason": "not needed"})

        resp = admin.post(f"/purchases/incoming/{event_id}/approve", data={
            "_csrf_token": token, "branchId": branch_id,
            "itemId": item["id"], "qty": "10", "rate": "72",
        }, follow_redirects=True)
        assert b"already been reviewed" in resp.data
