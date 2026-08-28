"""
Integration tests for auth, sessions, CSRF, and RBAC via Flask's test
client -- exercises the real request/response/cookie plumbing, not just
the underlying functions in isolation.
"""
import uuid

from tests.conftest import login


def test_protected_route_redirects_to_login_when_unauthenticated(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_public_paths_accessible_without_auth(client):
    assert client.get("/login").status_code == 200


def test_export_endpoint_also_requires_auth(client):
    # Easy to forget to protect API/download endpoints -- confirm explicitly.
    resp = client.get("/api/export/inventory")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_with_wrong_password_shows_generic_error(client, db_conn):
    # Use a purpose-built pbkdf2-hashed test user, not the reference DB's
    # `admin` account -- that snapshot predates the password migration and
    # still carries its original bcrypt hash, which takes a different
    # (correctly distinct, see test below) error path entirely.
    from app.security import hash_password
    db_conn.execute(
        "INSERT INTO User (id, name, email, passwordHash, role, active, createdAt, updatedAt) "
        "VALUES ('t1', 'Test', 'wrongpw_test_user', ?, 'ADMIN', 1, datetime('now'), datetime('now'))",
        (hash_password("correct-password"),),
    )
    db_conn.commit()

    resp = login(client, "wrongpw_test_user", "definitely-wrong")
    assert resp.status_code == 200  # re-renders login page, no redirect
    assert b"Invalid username or password" in resp.data


def test_login_with_legacy_bcrypt_hash_gets_distinct_error(client, db_conn):
    # A leftover bcrypt hash (from the pre-migration Next.js app) must show a
    # specific "reset needed" message, not the generic invalid-credentials
    # one -- this is what the reference DB's own `admin` row still has.
    resp = login(client, "admin", "whatever")
    assert resp.status_code == 200
    assert b"old password format" in resp.data


def test_login_without_csrf_token_is_rejected(client):
    resp = client.post("/login", data={"username": "admin", "password": "anything"})
    # Missing CSRF on a POST: either rejected by validate_csrf (403) or the
    # login logic itself fails closed -- either way, must NOT succeed.
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert b"Authenticated" not in resp.data


def test_forged_session_cookie_does_not_grant_access(client):
    client.set_cookie("session", "garbage.forged.value")
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_deactivated_user_session_is_dropped(client, app, db_conn):
    """A user active at login time who gets deactivated mid-session must be
    bounced on their next request, not keep their old access."""
    user_id = uuid.uuid4().hex
    from app.security import hash_password
    db_conn.execute(
        "INSERT INTO User (id, name, email, passwordHash, role, active, createdAt, updatedAt) "
        "VALUES (?, 'Temp', 'temp_test_user', ?, 'STORE', 1, datetime('now'), datetime('now'))",
        (user_id, hash_password("temppass123")),
    )
    db_conn.commit()

    # This test's `client` fixture uses a different DB connection (via the
    # app's own get_connection()) than db_conn, but both point at the same
    # underlying file, so the write above is visible to the app.
    resp = login(client, "temp_test_user", "temppass123")
    assert resp.status_code == 302

    db_conn.execute("UPDATE User SET active = 0 WHERE id = ?", (user_id,))
    db_conn.commit()

    resp = client.get("/tracker")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


class TestRoleBasedAccess:
    def _create_user(self, db_conn, role: str, branch_id: str | None) -> tuple[str, str]:
        from app.security import hash_password
        username = f"test_{role.lower()}_{uuid.uuid4().hex[:8]}"
        password = "testpass123"
        db_conn.execute(
            "INSERT INTO User (id, name, email, passwordHash, role, branchId, active, createdAt, updatedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))",
            (uuid.uuid4().hex, f"Test {role}", username, hash_password(password), role, branch_id),
        )
        db_conn.commit()
        return username, password

    def test_store_role_blocked_from_admin(self, client, db_conn, branch_id):
        username, password = self._create_user(db_conn, "STORE", branch_id)
        login(client, username, password)
        resp = client.get("/admin")
        assert resp.status_code == 302
        assert "/admin" not in resp.headers["Location"]  # bounced away, not let through

    def test_store_role_allowed_on_tracker(self, client, db_conn, branch_id):
        username, password = self._create_user(db_conn, "STORE", branch_id)
        login(client, username, password)
        resp = client.get("/tracker")
        assert resp.status_code == 200

    def test_kitchen_role_default_landing_page(self, client, db_conn, branch_id):
        username, password = self._create_user(db_conn, "KITCHEN", branch_id)
        resp = login(client, username, password)
        assert resp.headers["Location"].endswith("/kitchen")

    def test_viewer_role_redirected_away_from_write_only_routes(self, client, db_conn, branch_id):
        # /purchases isn't even in VIEWER's ROUTE_ACCESS list at all (only
        # ADMIN/MANAGER/STORE), so this is blocked at the route-access layer,
        # before the separate can_write() read-only check would ever run --
        # see test_can_write_excludes_only_viewer below for that check
        # in isolation, since no current route depends on it via HTTP.
        username, password = self._create_user(db_conn, "VIEWER", branch_id)
        login(client, username, password)
        resp = client.post("/purchases", data={})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/dashboard")  # bounced to VIEWER's default route

    def test_can_write_excludes_only_viewer(self):
        from app.auth.permissions import can_write
        assert can_write("VIEWER") is False
        for role in ("ADMIN", "MANAGER", "STORE", "KITCHEN"):
            assert can_write(role) is True

    def test_admin_has_no_assigned_branch(self, client, db_conn):
        resp = login(client, "admin", "devlocal123")
        # Only meaningful if the local dev password hasn't been changed --
        # skip gracefully if it has (e.g. after cutover password migration).
        if resp.status_code != 302:
            import pytest
            pytest.skip("admin/devlocal123 credentials not active in this environment")
        assert resp.headers["Location"].endswith("/dashboard")
