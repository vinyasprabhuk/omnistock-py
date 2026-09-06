"""e2e coverage for the mobile Opening Stock tab: KITCHEN can reach and
save on it (unlike the financial Master Inventory report, which stays
closed to KITCHEN), the save endpoint's validation, and the voice-match
endpoint reusing match_item against real Item Master names/aliases."""
from __future__ import annotations

from tests.conftest import csrf_token, login, make_user


def _admin_client(full_app, full_db_conn, branch_id):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


def _kitchen_client(full_app, full_db_conn, branch_id):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
    login(client, username, password)
    return client


class TestOpeningStockAccess:
    def test_kitchen_role_can_access_opening_stock_page(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        resp = client.get("/opening-stock")
        assert resp.status_code == 200
        assert b"Opening Stock" in resp.data

    def test_kitchen_role_cannot_access_master_inventory_report(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        resp = client.get("/inventory")
        assert resp.status_code == 302, "KITCHEN must stay blocked from the financial report"

    def test_viewer_role_has_no_access_to_opening_stock_at_all(self, full_app, full_db_conn, branch_id):
        # VIEWER isn't in this route's allowed roles (ADMIN/MANAGER/STORE/
        # KITCHEN) -- blocked at the route-access level (302), never even
        # reaching the read-only/write check.
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "VIEWER", branch_id)
        login(client, username, password)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        token = csrf_token(client)
        resp = client.post(f"/opening-stock/{item['id']}/save",
                            data={"_csrf_token": token, "branchId": branch_id, "qty": "5"})
        assert resp.status_code == 302
        get_resp = client.get("/opening-stock")
        assert get_resp.status_code == 302


class TestOpeningStockSave:
    def test_save_creates_new_row_for_item_with_no_prior_opening_stock(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute(
            "SELECT id FROM Item WHERE active = 1 AND id NOT IN "
            "(SELECT itemId FROM ItemOpeningStock WHERE branchId = ?) LIMIT 1", (branch_id,)
        ).fetchone()
        assert item is not None, "fixture needs at least one item with no existing opening stock row"
        token = csrf_token(client)

        resp = client.post(f"/opening-stock/{item['id']}/save",
                            data={"_csrf_token": token, "branchId": branch_id, "qty": "12.5"},
                            headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "itemId": item["id"], "qty": 12.5}

        row = full_db_conn.execute(
            "SELECT qty FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (item["id"], branch_id)
        ).fetchone()
        assert row["qty"] == 12.5

    def test_save_updates_existing_row_not_duplicate(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        token = csrf_token(client)

        client.post(f"/opening-stock/{item['id']}/save",
                    data={"_csrf_token": token, "branchId": branch_id, "qty": "3"},
                    headers={"X-Requested-With": "XMLHttpRequest"})
        client.post(f"/opening-stock/{item['id']}/save",
                    data={"_csrf_token": token, "branchId": branch_id, "qty": "8"},
                    headers={"X-Requested-With": "XMLHttpRequest"})

        rows = full_db_conn.execute(
            "SELECT qty FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (item["id"], branch_id)
        ).fetchall()
        assert len(rows) == 1, "second save must update, not insert a duplicate row"
        assert rows[0]["qty"] == 8.0

    def test_save_rejects_negative_qty(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        token = csrf_token(client)

        resp = client.post(f"/opening-stock/{item['id']}/save",
                            data={"_csrf_token": token, "branchId": branch_id, "qty": "-5"},
                            headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 400
        assert "negative" in resp.get_json()["error"]

    def test_save_rejects_non_numeric_qty(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute("SELECT id FROM Item WHERE active = 1 LIMIT 1").fetchone()
        token = csrf_token(client)

        resp = client.post(f"/opening-stock/{item['id']}/save",
                            data={"_csrf_token": token, "branchId": branch_id, "qty": "not-a-number"},
                            headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 400

    def test_save_rejects_unknown_item_id(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = client.post("/opening-stock/does-not-exist/save",
                            data={"_csrf_token": token, "branchId": branch_id, "qty": "5"},
                            headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"].lower()

    def test_updated_opening_stock_reflected_on_daily_tracker(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 1").fetchone()
        token = csrf_token(client)
        client.post(f"/opening-stock/{item['id']}/save",
                    data={"_csrf_token": token, "branchId": branch_id, "qty": "42"},
                    headers={"X-Requested-With": "XMLHttpRequest"})

        admin = _admin_client(full_app, full_db_conn, branch_id)
        resp = admin.get(f"/tracker?date=2026-08-25&branchId={branch_id}")
        assert item["name"].encode() in resp.data


class TestVoiceMatch:
    def test_voice_match_finds_item_by_exact_name(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute("SELECT id, name FROM Item WHERE name = 'Sugar' LIMIT 1").fetchone()
        assert item is not None, "fixture depends on 'Sugar' existing in the pristine Item Master"
        token = csrf_token(client)

        resp = client.post("/opening-stock/voice-match",
                            data='{"text": "sugar"}',
                            content_type="application/json",
                            headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["matchedItemId"] == item["id"]
        assert data["confidence"] >= 90

    def test_voice_match_finds_item_by_alias(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        item = full_db_conn.execute("SELECT id FROM Item WHERE name = 'Sugar' LIMIT 1").fetchone()
        from app.db import new_id
        full_db_conn.execute(
            "INSERT INTO ItemAlias (id, itemId, alias, createdAt) VALUES (?, ?, ?, datetime('now'))",
            (new_id(), item["id"], "sakkarai"),
        )
        full_db_conn.commit()
        token = csrf_token(client)

        resp = client.post("/opening-stock/voice-match",
                            data='{"text": "sakkarai"}',
                            content_type="application/json",
                            headers={"X-CSRF-Token": token})
        data = resp.get_json()
        assert data["matchedItemId"] == item["id"]

    def test_voice_match_empty_text_is_rejected(self, full_app, full_db_conn, branch_id):
        client = _kitchen_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = client.post("/opening-stock/voice-match",
                            data='{"text": ""}',
                            content_type="application/json",
                            headers={"X-CSRF-Token": token})
        assert resp.status_code == 400
