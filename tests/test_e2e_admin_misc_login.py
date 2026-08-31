"""e2e coverage for remaining Admin pages (hub, status, audit-log,
wastage-menu), the Kitchen manual-entry path, and login/logout/csrf
edge cases not already covered by test_auth.py."""
from __future__ import annotations

from tests.conftest import csrf_token, login, make_user


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestAdminHubAndStatus:
    def test_hub_lists_every_section(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        resp = client.get("/admin")
        assert resp.status_code == 200
        for label in ("Item Master", "Users", "System Status", "Audit Log", "Branding"):
            assert label.encode() in resp.data

    def test_status_page_loads(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        resp = client.get("/admin/status")
        assert resp.status_code == 200

    def test_audit_log_shows_a_real_write_action(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        client.post("/admin/departments/create", data={"_csrf_token": token, "name": "Audit Test Dept"})

        resp = client.get("/admin/audit-log")
        assert resp.status_code == 200
        assert b"/admin/departments/create" in resp.data or b"POST" in resp.data


class TestWastageMenuCRUD:
    def test_create_and_delete_wastage_menu_item(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/admin/wastage-menu/create", data={
            "_csrf_token": token, "mealPeriod": "BREAKFAST", "name": "Test Menu Dish",
        }, follow_redirects=True)
        assert resp.status_code == 200
        # create_wastage_menu_item stores the name uppercased.
        item = full_db_conn.execute("SELECT id FROM WastageMenuItem WHERE name = 'TEST MENU DISH'").fetchone()
        assert item is not None

        del_resp = client.post(f"/admin/wastage-menu/{item['id']}/delete", data={"_csrf_token": token},
                                follow_redirects=True)
        assert del_resp.status_code == 200
        gone = full_db_conn.execute("SELECT active FROM WastageMenuItem WHERE id = ?", (item["id"],)).fetchone()
        assert gone is None or gone["active"] == 0


class TestKitchenManualEntry:
    def test_manual_entry_creates_requirement_and_redirects_to_review(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/kitchen/manual-entry", data={
            "_csrf_token": token, "date": "2026-08-25",
            "departmentName": "SOUTH INDIAN", "itemId": item["id"], "qty": "3",
        })
        assert resp.status_code == 302
        assert "/kitchen/review/" in resp.headers["Location"]
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        row = full_db_conn.execute(
            "SELECT qty, status, confidence FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchone()
        assert row["qty"] == 3.0
        assert row["status"] == "AUTO"
        assert row["confidence"] == 100

    def test_manual_entry_with_no_lines_shows_error(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        resp = client.post("/kitchen/manual-entry", data={"_csrf_token": token, "date": "2026-08-25"},
                            follow_redirects=True)
        assert b"Add at least one item" in resp.data


class TestLoginLogoutCsrf:
    def test_logout_clears_session(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "STORE", branch_id)
        login(client, username, password)
        assert client.get("/tracker").status_code == 200

        token = csrf_token(client)
        client.post("/logout", data={"_csrf_token": token})
        resp = client.get("/tracker")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_csrf_token_api_requires_auth(self, full_app):
        # The global before_request RBAC gate redirects any unauthenticated
        # request to a non-public path before this route's own body (and
        # its 401 branch) ever runs -- same as every other route, so the
        # observable behavior is a redirect, not a 401.
        client = full_app.test_client()
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_csrf_token_api_returns_usable_token(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "STORE", branch_id)
        login(client, username, password)
        token = client.get("/api/csrf-token").get_json()["csrfToken"]
        assert isinstance(token, str) and len(token) > 10

    def test_login_get_redirects_when_already_authenticated(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "STORE", branch_id)
        login(client, username, password)
        resp = client.get("/login")
        assert resp.status_code == 302
