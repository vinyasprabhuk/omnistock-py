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


class TestKitchenRequestEntry:
    """The Request Regular/Extra Items flow that replaced the old flat
    'manual entry' page -- multi-department, one requirement per
    Regular/Extra session: each department's Save appends to a running
    Pending KitchenRequirement, and Submit (once at least one department
    is saved) just navigates to the review page -- nothing new to write,
    since every Save already persisted."""

    def test_save_creates_pending_requirement_and_returns_to_department_picker(
        self, full_app, full_db_conn, branch_id
    ):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": dept["id"],
            "date": "2026-08-25", "branchId": branch_id,
            "itemId": [item["id"]], "qty": ["3"],
        })
        assert resp.status_code == 302
        assert "/kitchen/request?" in resp.headers["Location"]
        assert "requirementId=" in resp.headers["Location"]
        requirement_id = resp.headers["Location"].rsplit("requirementId=", 1)[-1]

        row = full_db_conn.execute(
            "SELECT qty, status, confidence FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchone()
        assert row["qty"] == 3.0
        assert row["status"] == "AUTO"
        assert row["confidence"] == 100
        req_row = full_db_conn.execute(
            "SELECT status, requestType FROM KitchenRequirement WHERE id = ?", (requirement_id,)
        ).fetchone()
        assert req_row["status"] == "PENDING"
        assert req_row["requestType"] == "REGULAR"

    def test_second_department_save_appends_to_same_requirement(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        items = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 2").fetchall()
        depts = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 AND name != 'Historical Import' LIMIT 2").fetchall()

        resp1 = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": depts[0]["id"],
            "date": "2026-08-25", "branchId": branch_id,
            "itemId": [items[0]["id"]], "qty": ["3"],
        })
        requirement_id = resp1.headers["Location"].rsplit("requirementId=", 1)[-1]

        resp2 = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": depts[1]["id"],
            "date": "2026-08-25", "branchId": branch_id, "requirementId": requirement_id,
            "itemId": [items[1]["id"]], "qty": ["2"],
        })
        assert requirement_id in resp2.headers["Location"], "must still be the same one requirement/transaction"

        rows = full_db_conn.execute(
            "SELECT DISTINCT departmentId FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchall()
        assert len(rows) == 2, "both departments' items live under the same single requirement"
        count = full_db_conn.execute("SELECT COUNT(*) c FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()["c"]
        assert count == 1, "still exactly one KitchenRequirement row -- one transaction"

    def test_cannot_save_department_into_an_approved_requirement(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()
        resp1 = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": dept["id"],
            "date": "2026-08-25", "branchId": branch_id,
            "itemId": [item["id"]], "qty": ["3"],
        })
        requirement_id = resp1.headers["Location"].rsplit("requirementId=", 1)[-1]

        from app.services.kitchen_requirement import approve_kitchen_requirement
        admin_id, _, _ = make_user(full_db_conn, "ADMIN", None)
        approve_kitchen_requirement(full_db_conn, admin_id, requirement_id)

        resp2 = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": dept["id"],
            "date": "2026-08-25", "branchId": branch_id, "requirementId": requirement_id,
            "itemId": [item["id"]], "qty": ["9"],
        }, follow_redirects=True)
        assert b"no longer open" in resp2.data

    def test_blank_qty_lines_are_not_saved(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        items = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 2").fetchall()
        dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()

        resp = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "EXTRA", "departmentId": dept["id"],
            "date": "2026-08-25", "branchId": branch_id,
            "itemId": [items[0]["id"], items[1]["id"]], "qty": ["5", ""],
        })
        requirement_id = resp.headers["Location"].rsplit("requirementId=", 1)[-1]
        rows = full_db_conn.execute(
            "SELECT matchedItemId, qty FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchall()
        assert len(rows) == 1, "blank qty should not produce a row"
        assert rows[0]["matchedItemId"] == items[0]["id"]

    def test_no_lines_shows_error(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()
        resp = client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": dept["id"],
            "date": "2026-08-25", "branchId": branch_id,
        }, follow_redirects=True)
        assert b"Add at least one item" in resp.data

    def test_department_picker_then_item_entry_history_scoped(self, full_app, full_db_conn, branch_id):
        """A department with real request history only offers items seen
        under that department before (matching the real Excel template's
        department-scoped blocks); a brand-new department with none falls
        back to every active item."""
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()
        old_dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 AND name != 'Historical Import' LIMIT 1").fetchone()
        client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "REGULAR", "departmentId": old_dept["id"],
            "date": "2026-08-25", "branchId": branch_id,
            "itemId": [item["id"]], "qty": ["1"],
        })

        resp = client.get(f"/kitchen/request?type=regular&departmentId={old_dept['id']}")
        assert item["name"].encode() in resp.data

        from app.db import new_id
        new_dept_id = new_id()
        full_db_conn.execute(
            "INSERT INTO Department (id, name, active) VALUES (?, 'Brand New Dept', 1)",
            (new_dept_id,),
        )
        full_db_conn.commit()
        resp2 = client.get(f"/kitchen/request?type=regular&departmentId={new_dept_id}")
        assert b"every active item" in resp2.data

    def test_historical_import_department_excluded_from_picker(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        full_db_conn.execute(
            "INSERT OR IGNORE INTO Department (id, name, active) VALUES ('hist-import-test', 'Historical Import', 1)"
        )
        full_db_conn.commit()

        resp = client.get("/kitchen/request?type=regular")
        assert b"Historical Import" not in resp.data

    def test_pending_requests_shown_on_kitchen_index_grouped_by_type(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()
        client.post("/kitchen/request/save", data={
            "_csrf_token": token, "requestType": "EXTRA", "departmentId": dept["id"],
            "date": "2026-08-25", "branchId": branch_id,
            "itemId": [item["id"]], "qty": ["1"],
        })

        # The Pending list is scoped to whatever date the picker is on --
        # a request for 2026-08-25 shows up when viewing that date...
        resp = client.get("/kitchen?date=2026-08-25")
        assert resp.status_code == 200
        assert b"Pending" in resp.data
        assert b"Extra" in resp.data

        # ...but not when viewing an unrelated date.
        resp2 = client.get("/kitchen?date=2026-08-26")
        assert b"Pending" not in resp2.data


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
