"""End-to-end coverage for Purchases and Stock Issue -- the two core
transactional flows that Daily Tracker's Purchased/Issued columns and
Master Inventory's currentStock are computed from. Covers manual entry,
validation, the Excel preview -> commit path (reusing the same real
block-format generator as the kitchen requirement suite), and that a
saved transaction is actually visible on the Tracker afterward.
"""
from __future__ import annotations

import io

from tests.conftest import build_kitchen_upload_xlsx, csrf_token, login, make_user


def _admin_client(full_app, full_db_conn, branch_id):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestPurchasesManualEntry:
    def test_create_purchase_with_valid_lines(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/purchases", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "supplier": "Test Supplier",
            "itemId": item["id"], "qty": "10", "rate": "50",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Purchase saved" in resp.data

        row = full_db_conn.execute(
            "SELECT qty, rate FROM PurchaseItem pi JOIN Purchase p ON p.id = pi.purchaseId "
            "WHERE p.branchId = ? AND pi.itemId = ? ORDER BY p.createdAt DESC LIMIT 1",
            (branch_id, item["id"]),
        ).fetchone()
        assert row["qty"] == 10.0
        assert row["rate"] == 50.0

    def test_create_purchase_without_lines_shows_error_and_saves_nothing(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        before = full_db_conn.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0]

        resp = client.post("/purchases", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
        }, follow_redirects=True)
        assert b"Add at least one line item" in resp.data
        after = full_db_conn.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0]
        assert after == before

    def test_purchase_visible_on_tracker_afterward(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()

        client.post("/purchases", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "qty": "15", "rate": "20",
        })
        resp = client.get(f"/tracker?date=2026-08-25&branchId={branch_id}")
        assert resp.status_code == 200
        assert item["name"].encode() in resp.data


class TestStockIssueManualEntry:
    def test_create_issue_requires_department(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/issue", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "qty": "3",
        }, follow_redirects=True)
        assert b"Department is required" in resp.data

    def test_create_issue_creates_stock_issue_row(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/issue", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "departmentName": "SOUTH INDIAN", "itemId": item["id"], "qty": "4",
        }, follow_redirects=True)
        assert b"Stock issue saved" in resp.data
        row = full_db_conn.execute(
            "SELECT qty FROM StockIssueItem sii JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.branchId = ? AND sii.itemId = ? ORDER BY si.createdAt DESC LIMIT 1",
            (branch_id, item["id"]),
        ).fetchone()
        assert row["qty"] == 4.0

    def test_store_role_can_create_issue_kitchen_role_cannot_access_page(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "STORE", branch_id)
        login(client, username, password)
        assert client.get("/issue").status_code == 200

        client2 = full_app.test_client()
        _, username2, password2 = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client2, username2, password2)
        resp = client2.get("/issue")
        assert resp.status_code == 302  # KITCHEN isn't in /issue's ROUTE_ACCESS


class TestExcelPreviewAndCommit:
    def test_purchase_excel_preview_then_commit(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name, unit FROM Item WHERE name = 'Sugar' LIMIT 1").fetchone()
        assert item is not None, "fixture depends on 'Sugar' existing in the pristine Item Master"
        data = build_kitchen_upload_xlsx({"SOUTH INDIAN": [("Sugar", 5.0, item["unit"])]})

        preview_resp = client.post("/purchases/preview", data={
            "_csrf_token": token, "date": "2026-08-25",
            "file": (io.BytesIO(data), "purchase.xlsx"),
        }, content_type="multipart/form-data")
        assert preview_resp.status_code == 200
        assert b"Sugar" in preview_resp.data

        before = full_db_conn.execute("SELECT COUNT(*) FROM PurchaseItem").fetchone()[0]
        commit_resp = client.post("/purchases/commit", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "qty": "5", "rate": "10",
        }, follow_redirects=True)
        assert commit_resp.status_code == 200
        after = full_db_conn.execute("SELECT COUNT(*) FROM PurchaseItem").fetchone()[0]
        assert after == before + 1

    def test_issue_excel_preview_then_commit(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name, unit FROM Item WHERE name = 'Sugar' LIMIT 1").fetchone()
        data = build_kitchen_upload_xlsx({"CHINESE": [("Sugar", 2.0, item["unit"])]})

        preview_resp = client.post("/issue/preview", data={
            "_csrf_token": token, "date": "2026-08-25",
            "file": (io.BytesIO(data), "issue.xlsx"),
        }, content_type="multipart/form-data")
        assert preview_resp.status_code == 200
        assert b"Sugar" in preview_resp.data

        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]
        commit_resp = client.post("/issue/commit", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "departmentName": "CHINESE", "itemId": item["id"], "qty": "2",
        }, follow_redirects=True)
        assert commit_resp.status_code == 200
        after = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]
        assert after == before + 1
