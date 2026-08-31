"""End-to-end coverage for core Admin CRUD: items, branches/departments
(including the delete-referenced-row guard), and users (every role,
deactivate, password reset).
"""
from __future__ import annotations

from tests.conftest import csrf_token, login, make_user


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestItemsCRUD:
    def test_create_item(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/admin/items/create", data={
            "_csrf_token": token, "name": "Admin Created Item", "unit": "KG",
            "purchasePrice": "25", "openingStock": "10", "branchId": branch_id,
        }, follow_redirects=True)
        assert b"Item added" in resp.data
        item = full_db_conn.execute("SELECT id, active FROM Item WHERE name = 'Admin Created Item'").fetchone()
        assert item is not None and item["active"] == 1
        opening = full_db_conn.execute(
            "SELECT qty FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (item["id"], branch_id)
        ).fetchone()
        assert opening["qty"] == 10.0

    def test_deactivate_item(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        client.post("/admin/items/create", data={
            "_csrf_token": token, "name": "Item To Deactivate", "unit": "KG",
            "purchasePrice": "5", "openingStock": "0", "branchId": branch_id,
        })
        item_id = full_db_conn.execute("SELECT id FROM Item WHERE name = 'Item To Deactivate'").fetchone()["id"]

        resp = client.post(f"/admin/items/{item_id}/deactivate", data={"_csrf_token": token}, follow_redirects=True)
        assert b"Item deactivated" in resp.data
        active = full_db_conn.execute("SELECT active FROM Item WHERE id = ?", (item_id,)).fetchone()["active"]
        assert active == 0

    def test_add_item_alias(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        resp = client.post(f"/admin/items/{item['id']}/alias", data={
            "_csrf_token": token, "alias": "Test Alias Name",
        }, follow_redirects=True)
        assert b"Alias added" in resp.data
        # admin_service.add_item_alias uppercases every alias before storing.
        alias = full_db_conn.execute(
            "SELECT alias FROM ItemAlias WHERE itemId = ? AND alias = 'TEST ALIAS NAME'", (item["id"],)
        ).fetchone()
        assert alias is not None


class TestDepartmentsGuard:
    def test_delete_unused_department_succeeds(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        client.post("/admin/departments/create", data={"_csrf_token": token, "name": "Unused Test Dept"})
        dept_id = full_db_conn.execute("SELECT id FROM Department WHERE name = 'Unused Test Dept'").fetchone()["id"]

        resp = client.post(f"/admin/departments/{dept_id}/delete", data={"_csrf_token": token}, follow_redirects=True)
        assert b"Department deleted" in resp.data
        still_active = full_db_conn.execute("SELECT active FROM Department WHERE id = ?", (dept_id,)).fetchone()
        assert still_active is None or still_active["active"] == 0

    def test_delete_department_in_use_by_stock_issue_is_blocked(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        client.post("/admin/departments/create", data={"_csrf_token": token, "name": "In Use Test Dept"})
        dept_id = full_db_conn.execute("SELECT id FROM Department WHERE name = 'In Use Test Dept'").fetchone()["id"]
        full_db_conn.execute(
            "INSERT INTO StockIssue (id, date, branchId, departmentId, createdAt) "
            "VALUES ('guard-si', '2026-08-25T00:00:00.000+00:00', ?, ?, datetime('now'))",
            (branch_id, dept_id),
        )
        full_db_conn.commit()

        resp = client.post(f"/admin/departments/{dept_id}/delete", data={"_csrf_token": token}, follow_redirects=True)
        assert b"Department deleted" not in resp.data
        row = full_db_conn.execute("SELECT * FROM Department WHERE id = ?", (dept_id,)).fetchone()
        assert row is not None, "in-use department must not be deleted"


class TestUsersCRUD:
    def test_create_user_of_each_role(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        for role in ("MANAGER", "STORE", "KITCHEN", "VIEWER"):
            resp = client.post("/admin/users/create", data={
                "_csrf_token": token, "name": f"Test {role}", "email": f"crud_{role.lower()}@test.local",
                "password": "testpass123", "role": role, "branchId": branch_id,
            }, follow_redirects=True)
            assert b"User created" in resp.data
            row = full_db_conn.execute(
                "SELECT role, active FROM User WHERE email = ?", (f"crud_{role.lower()}@test.local",)
            ).fetchone()
            assert row["role"] == role
            assert row["active"] == 1

    def test_new_user_can_actually_log_in(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        client.post("/admin/users/create", data={
            "_csrf_token": token, "name": "Login Test User", "email": "login_test_user@test.local",
            "password": "brandnewpass123", "role": "STORE", "branchId": branch_id,
        })
        login_client = full_app.test_client()
        resp = login(login_client, "login_test_user@test.local", "brandnewpass123")
        assert resp.status_code == 302

    def test_deactivate_user_blocks_further_login(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        user_id, username, password = make_user(full_db_conn, "STORE", branch_id)

        resp = client.post(f"/admin/users/{user_id}/deactivate", data={"_csrf_token": token}, follow_redirects=True)
        assert b"User deactivated" in resp.data

        login_client = full_app.test_client()
        login_resp = login(login_client, username, password)
        assert login_resp.status_code == 200  # re-renders login page, not a successful redirect

    def test_reset_password_lets_user_log_in_with_new_password(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        user_id, username, old_password = make_user(full_db_conn, "STORE", branch_id)

        resp = client.post(f"/admin/users/{user_id}/reset-password", data={
            "_csrf_token": token, "newPassword": "resetpassword456",
        }, follow_redirects=True)
        assert b"Password reset" in resp.data

        login_client = full_app.test_client()
        old_login = login(login_client, username, old_password)
        assert old_login.status_code == 200  # old password no longer works

        login_client2 = full_app.test_client()
        new_login = login(login_client2, username, "resetpassword456")
        assert new_login.status_code == 302
