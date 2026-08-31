"""End-to-end coverage of actually logging a Wastage/Production entry
(photo required, role-gated to Kitchen/Admin/Manager/Department Lead)
and deleting one. Read-only visibility and the analysis cards are
already covered by test_e2e_nav_rbac.py and test_e2e_variance.py.
"""
from __future__ import annotations

import io

from tests.conftest import csrf_token, login, make_user


def _create_entry(client, token, branch_id, mode="production", weight="2", description="Test Sambar",
                   date="2026-08-25"):
    return client.post("/wastage/create", data={
        "_csrf_token": token, "mode": mode, "date": date, "branchId": branch_id,
        "customName": description, "weight": weight, "unit": "KG",
        "photo": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 20), "photo.png"),
    }, content_type="multipart/form-data", follow_redirects=True)


class TestLoggingRoleGate:
    def test_kitchen_can_log_production(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        resp = _create_entry(client, token, branch_id)
        assert b"logged" in resp.data
        row = full_db_conn.execute(
            "SELECT weight, unit FROM ProductionLog WHERE branchId = ? AND description = 'Test Sambar'", (branch_id,)
        ).fetchone()
        assert row["weight"] == 2.0
        assert row["unit"] == "KG"

    def test_manager_can_log_wastage(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "MANAGER", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        resp = _create_entry(client, token, branch_id, mode="wastage", description="Manager Logged Waste")
        assert b"logged" in resp.data
        row = full_db_conn.execute(
            "SELECT COUNT(*) FROM Wastage WHERE branchId = ? AND description = 'Manager Logged Waste'", (branch_id,)
        ).fetchone()[0]
        assert row == 1

    def test_store_cannot_reach_wastage_page_at_all(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "STORE", branch_id)
        login(client, username, password)
        resp = client.get("/wastage")
        assert resp.status_code == 302

    def test_viewer_role_cannot_log_even_if_it_could_reach_the_page(self, full_app, full_db_conn, branch_id):
        # VIEWER isn't in /wastage's ROUTE_ACCESS at all, so this is
        # blocked at the route layer before require_write's read-only
        # check would ever run -- confirms the outer gate, not the inner
        # one (that's covered directly in test_auth.py).
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "VIEWER", branch_id)
        login(client, username, password)
        resp = client.get("/wastage")
        assert resp.status_code == 302

    def test_photo_is_required(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        resp = client.post("/wastage/create", data={
            "_csrf_token": token, "mode": "production", "date": "2026-08-25", "branchId": branch_id,
            "customName": "No Photo Entry", "weight": "1", "unit": "KG",
        }, content_type="multipart/form-data", follow_redirects=True)
        assert b"Photo is required" in resp.data
        count = full_db_conn.execute(
            "SELECT COUNT(*) FROM ProductionLog WHERE description = 'No Photo Entry'"
        ).fetchone()[0]
        assert count == 0


class TestDeleteEntry:
    def test_admin_can_delete_a_logged_entry(self, full_app, full_db_conn, branch_id):
        kitchen_client = full_app.test_client()
        _, kuser, kpass = make_user(full_db_conn, "KITCHEN", branch_id)
        login(kitchen_client, kuser, kpass)
        ktoken = csrf_token(kitchen_client)
        _create_entry(kitchen_client, ktoken, branch_id, description="To Be Deleted")

        entry_id = full_db_conn.execute(
            "SELECT id FROM ProductionLog WHERE description = 'To Be Deleted'"
        ).fetchone()["id"]

        admin_client = full_app.test_client()
        _, auser, apass = make_user(full_db_conn, "ADMIN", None)
        login(admin_client, auser, apass)
        atoken = csrf_token(admin_client)
        resp = admin_client.post(f"/wastage/{entry_id}/delete", data={
            "_csrf_token": atoken, "mode": "production", "date": "2026-08-25", "branchId": branch_id,
        }, follow_redirects=True)
        assert b"Entry deleted" in resp.data
        remaining = full_db_conn.execute("SELECT COUNT(*) FROM ProductionLog WHERE id = ?", (entry_id,)).fetchone()[0]
        assert remaining == 0
