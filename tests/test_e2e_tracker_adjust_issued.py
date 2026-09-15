"""Daily Tracker's Admin-only "Add Issued Correction" action -- posts a
real StockIssue/StockIssueItem row (the exact same transaction manual
Stock Issue entry and Kitchen Requirement Issue both create), so the
correction flows into the Issued/Closing columns through the same
summed aggregate rather than a separate override field."""
from __future__ import annotations

from tests.conftest import csrf_token, login, make_user


def _client(full_app, full_db_conn, role, branch_id=None):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, role, branch_id)
    login(client, username, password)
    return client


class TestTrackerAdjustIssued:
    def test_admin_can_add_issued_correction(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "6",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Issued quantity added" in resp.data

        row = full_db_conn.execute(
            "SELECT qty FROM StockIssueItem sii JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.branchId = ? AND sii.itemId = ? ORDER BY si.createdAt DESC LIMIT 1",
            (branch_id, item["id"]),
        ).fetchone()
        assert row["qty"] == 6.0

    def test_correction_is_reflected_in_tracker_issued_and_closing(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()

        before = full_db_conn.execute(
            "SELECT COALESCE(SUM(sii.qty), 0) AS total FROM StockIssueItem sii "
            "JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.branchId = ? AND sii.itemId = ? AND si.date = '2026-08-26T00:00:00.000+00:00'",
            (branch_id, item["id"]),
        ).fetchone()["total"]

        client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-26", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "9",
        })

        after = full_db_conn.execute(
            "SELECT COALESCE(SUM(sii.qty), 0) AS total FROM StockIssueItem sii "
            "JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.branchId = ? AND sii.itemId = ? AND si.date = '2026-08-26T00:00:00.000+00:00'",
            (branch_id, item["id"]),
        ).fetchone()["total"]
        assert after == before + 9.0

    def test_zero_or_negative_qty_is_rejected(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "0",
        }, follow_redirects=True)
        assert b"quantity greater than zero" in resp.data
        after = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]
        assert after == before

    def test_missing_department_is_rejected(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "", "qty": "5",
        }, follow_redirects=True)
        assert b"Department is required" in resp.data

    def test_non_admin_is_blocked(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "STORE", branch_id)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "5",
        })
        assert resp.status_code == 403
        after = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]
        assert after == before

    def test_edit_button_visible_to_admin_not_to_viewer(self, full_app, full_db_conn, branch_id):
        admin = _client(full_app, full_db_conn, "ADMIN")
        resp = admin.get(f"/tracker?date=2026-08-25&branchId={branch_id}")
        assert b"js-adjust-issued" in resp.data

        viewer = _client(full_app, full_db_conn, "VIEWER", branch_id)
        resp2 = viewer.get(f"/tracker?date=2026-08-25&branchId={branch_id}")
        assert resp2.status_code == 200
        assert b"js-adjust-issued" not in resp2.data
