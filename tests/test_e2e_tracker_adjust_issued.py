"""Daily Tracker's Admin-only "Edit Issued" action -- the dialog
pre-fills the item's current Issued total for that day, and whatever
the admin types becomes the new total. Since Issued is a summed
aggregate over however many real StockIssueItem rows exist for that
item/date (not a single editable field), this is implemented by
posting one more correcting StockIssueItem for the DIFFERENCE between
the typed total and the current total -- the same real transaction
manual Stock Issue entry and Kitchen Requirement Issue both create, so
it flows into Issued/Closing through the same summed aggregate rather
than a separate override field. The correction can be negative
(reducing a wrongly-high total, e.g. Kitchen logged 500 instead of 0.5)."""
from __future__ import annotations

from tests.conftest import csrf_token, login, make_user


def _client(full_app, full_db_conn, role, branch_id=None):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, role, branch_id)
    login(client, username, password)
    return client


def _issued_total(full_db_conn, branch_id, item_id, date_db):
    return full_db_conn.execute(
        "SELECT COALESCE(SUM(sii.qty), 0) AS total FROM StockIssueItem sii "
        "JOIN StockIssue si ON si.id = sii.stockIssueId "
        "WHERE si.branchId = ? AND sii.itemId = ? AND si.date = ?",
        (branch_id, item_id, date_db),
    ).fetchone()["total"]


class TestTrackerEditIssued:
    def test_setting_issued_from_zero_creates_the_full_amount(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "6",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Issued quantity updated" in resp.data
        assert _issued_total(full_db_conn, branch_id, item["id"], "2026-08-25T00:00:00.000+00:00") == 6.0

    def test_editing_issued_upward_lands_on_the_typed_total(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()

        client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-26", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "4",
        })
        client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-26", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "13",
        })
        assert _issued_total(full_db_conn, branch_id, item["id"], "2026-08-26T00:00:00.000+00:00") == 13.0

    def test_editing_issued_down_fixes_a_wrong_existing_entry(self, full_app, full_db_conn, branch_id):
        """Real scenario this feature exists for: Kitchen logged 500
        instead of 0.5. Admin opens the (pre-filled 500) dialog and types
        0.5 -- the Tracker's Issued total must land on 0.5, not 500.5."""
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()

        client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-27", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Dosa", "qty": "500",
        })
        assert _issued_total(full_db_conn, branch_id, item["id"], "2026-08-27T00:00:00.000+00:00") == 500.0

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-27", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "0.5",
        }, follow_redirects=True)
        assert b"Issued quantity updated" in resp.data
        assert _issued_total(full_db_conn, branch_id, item["id"], "2026-08-27T00:00:00.000+00:00") == 0.5

    def test_typing_the_same_value_is_a_no_op(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()

        client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-28", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "8",
        })
        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-28", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "8",
        }, follow_redirects=True)
        assert b"already at that value" in resp.data
        after = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]
        assert after == before

    def test_negative_typed_total_is_rejected(self, full_app, full_db_conn, branch_id):
        client = _client(full_app, full_db_conn, "ADMIN")
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssueItem").fetchone()[0]

        resp = client.post("/tracker/adjust-issued", data={
            "_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
            "itemId": item["id"], "departmentName": "Historical Import", "qty": "-3",
        }, follow_redirects=True)
        assert b"Enter a valid quantity" in resp.data
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
