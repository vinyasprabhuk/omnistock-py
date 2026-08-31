"""e2e coverage for Recipe page rendering, Admin Branding settings,
authenticated file-serving routes, and the small PWA/inventory routes."""
from __future__ import annotations

import io

from app.dates import date_key_to_db
from app.db import new_id
from tests.conftest import csrf_token, login, make_user


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestRecipePage:
    def test_recipe_index_shows_seeded_recipe_and_ingredient_line(self, full_app, full_db_conn):
        item_id = new_id()
        full_db_conn.execute(
            "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
            "VALUES (?, 'Recipe Page Item', 'KG', 5, 'TEST', 1, datetime('now'), datetime('now'))",
            (item_id,),
        )
        dept = full_db_conn.execute("SELECT id FROM Department LIMIT 1").fetchone()["id"]
        dish_id = new_id()
        full_db_conn.execute(
            "INSERT INTO Dish (id, name, departmentId, category, menuGroup, active, createdAt, updatedAt) "
            "VALUES (?, 'Recipe Page Dish', ?, 'OTHER', 'Test Group', 1, datetime('now'), datetime('now'))",
            (dish_id, dept),
        )
        recipe_id = new_id()
        full_db_conn.execute(
            "INSERT INTO Recipe (id, dishId, name, servesQty, createdAt, updatedAt) "
            "VALUES (?, ?, 'Recipe Page Dish', 4, datetime('now'), datetime('now'))",
            (recipe_id, dish_id),
        )
        full_db_conn.execute(
            "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, "
            "matchStatus, createdAt) VALUES (?, ?, ?, 2, 'Recipe Page Item', 2, 'KG', 'AUTO', datetime('now'))",
            (new_id(), recipe_id, item_id),
        )
        full_db_conn.commit()

        client = _admin_client(full_app, full_db_conn)
        resp = client.get("/recipe")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Recipe Page Dish" in body
        assert "Recipe Page Item" in body

    def test_dish_without_recipe_appears_in_gap_list(self, full_app, full_db_conn):
        dept = full_db_conn.execute("SELECT id FROM Department LIMIT 1").fetchone()["id"]
        dish_id = new_id()
        full_db_conn.execute(
            "INSERT INTO Dish (id, name, departmentId, category, menuGroup, active, createdAt, updatedAt) "
            "VALUES (?, 'Gap Dish', ?, 'OTHER', 'Gap Group', 1, datetime('now'), datetime('now'))",
            (dish_id, dept),
        )
        full_db_conn.commit()
        client = _admin_client(full_app, full_db_conn)
        resp = client.get("/recipe")
        assert b"Gap Dish" in resp.data

    def test_upload_without_file_shows_error(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/recipe/upload", data={"_csrf_token": token}, follow_redirects=True)
        assert b"Choose a file first" in resp.data

    def test_upload_rejects_non_docx(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/recipe/upload", data={
            "_csrf_token": token, "file": (io.BytesIO(b"not a docx"), "recipe.txt"),
        }, content_type="multipart/form-data", follow_redirects=True)
        assert b"Only .docx recipe files are supported" in resp.data


class TestBrandingSettings:
    def test_update_app_name(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/admin/branding/app-name", data={
            "_csrf_token": token, "appName": "Test Brand Name", "tagline": "Test Tagline",
        }, follow_redirects=True)
        assert b"Saved" in resp.data
        row = full_db_conn.execute("SELECT appName, tagline FROM AppSettings LIMIT 1").fetchone()
        assert row["appName"] == "Test Brand Name"
        assert row["tagline"] == "Test Tagline"

    def test_update_header_color(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/admin/branding/header-color", data={
            "_csrf_token": token, "headerColor": "#123456",
        }, follow_redirects=True)
        assert b"Saved" in resp.data
        row = full_db_conn.execute("SELECT headerColor FROM AppSettings LIMIT 1").fetchone()
        assert row["headerColor"] == "#123456"

    def test_invalid_header_color_is_rejected(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/admin/branding/header-color", data={
            "_csrf_token": token, "headerColor": "not-a-color",
        }, follow_redirects=True)
        assert b"Saved" not in resp.data

    def test_update_theme(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/admin/branding/theme", data={
            "_csrf_token": token, "themeColor": "navy", "themeMode": "dark", "brandSize": "lg",
        }, follow_redirects=True)
        assert b"Theme saved" in resp.data
        row = full_db_conn.execute("SELECT themeMode, brandSize FROM AppSettings LIMIT 1").fetchone()
        assert row["themeMode"] == "dark"
        assert row["brandSize"] == "lg"

    def test_non_admin_cannot_reach_branding_page(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "MANAGER", branch_id)
        login(client, username, password)
        resp = client.get("/admin/branding")
        assert resp.status_code == 302


class TestFileServing:
    def test_wastage_photo_requires_branch_access(self, full_app, full_db_conn, branch_id):
        from app.services import storage
        saved = storage.save(b"fake-photo-bytes", "test.jpg")
        creator_id, _, _ = make_user(full_db_conn, "KITCHEN", branch_id)
        entry_id = new_id()
        full_db_conn.execute(
            "INSERT INTO Wastage (id, date, branchId, description, weight, unit, photoPath, photoMimeType, "
            "createdById, createdAt) VALUES (?, ?, ?, 'x', 1, 'KG', ?, 'image/jpeg', ?, datetime('now'))",
            (entry_id, date_key_to_db("2026-08-25"), branch_id, saved["filePath"], creator_id),
        )
        full_db_conn.commit()

        client = _admin_client(full_app, full_db_conn)
        resp = client.get(f"/api/wastage/photo/{entry_id}")
        assert resp.status_code == 200
        assert resp.data == b"fake-photo-bytes"

    def test_wastage_photo_404_for_missing_entry(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        resp = client.get("/api/wastage/photo/does-not-exist")
        assert resp.status_code == 404

    def test_branding_asset_is_public_without_login(self, full_app):
        client = full_app.test_client()
        resp = client.get("/branding/does-not-exist.png")
        assert resp.status_code == 404  # public route reached (not redirected to /login)


class TestPwaAndInventory:
    def test_manifest_json_is_public(self, full_app):
        client = full_app.test_client()
        resp = client.get("/manifest.json")
        assert resp.status_code == 200
        assert resp.get_json()["display"] == "standalone"

    def test_service_worker_is_public(self, full_app):
        client = full_app.test_client()
        resp = client.get("/sw.js")
        assert resp.status_code == 200
        assert resp.mimetype == "application/javascript"

    def test_asset_links_is_public_and_correct_shape(self, full_app):
        client = full_app.test_client()
        resp = client.get("/.well-known/assetlinks.json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data[0]["target"]["namespace"] == "android_app"

    def test_inventory_page_loads_for_store_role(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "STORE", branch_id)
        login(client, username, password)
        resp = client.get("/inventory")
        assert resp.status_code == 200
