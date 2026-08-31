"""e2e coverage for Intent's dish-override, ingredient-update, and
confirm mutation routes, plus the index GET page itself -- correctness
of the underlying prediction math is already covered by
test_e2e_intent.py; this covers the HTTP-level admin interactions."""
from __future__ import annotations

from app.db import new_id
from app.services.intent import generate_intent_day
from tests.conftest import csrf_token, login, make_user


def _setup_dish_with_sale(full_db_conn, name, item_name, qty_per_serve=1.0):
    item_id = new_id()
    full_db_conn.execute(
        "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, 'KG', 5, 'TEST', 1, datetime('now'), datetime('now'))",
        (item_id, item_name),
    )
    dept = full_db_conn.execute("SELECT id FROM Department LIMIT 1").fetchone()["id"]
    dish_id = new_id()
    full_db_conn.execute(
        "INSERT INTO Dish (id, name, departmentId, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, 'OTHER', 1, datetime('now'), datetime('now'))",
        (dish_id, name, dept),
    )
    recipe_id = new_id()
    full_db_conn.execute(
        "INSERT INTO Recipe (id, dishId, name, servesQty, createdAt, updatedAt) "
        "VALUES (?, ?, ?, 1, datetime('now'), datetime('now'))",
        (recipe_id, dish_id, name),
    )
    full_db_conn.execute(
        "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, "
        "matchStatus, createdAt) VALUES (?, ?, ?, ?, 'x', ?, 'KG', 'AUTO', datetime('now'))",
        (new_id(), recipe_id, item_id, qty_per_serve, qty_per_serve),
    )
    from app.dates import date_key_to_db
    full_db_conn.execute(
        "INSERT INTO DishSale (id, date, dishId, rawItemName, qty, matchStatus, createdAt) "
        "VALUES (?, ?, ?, 'x', 5, 'AUTO', datetime('now'))",
        (new_id(), date_key_to_db("2026-08-24"), dish_id),
    )
    full_db_conn.commit()
    return dish_id, item_id


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestIntentMutations:
    def test_dish_override_updates_final_qty(self, full_app, full_db_conn, branch_id):
        dish_id, _ = _setup_dish_with_sale(full_db_conn, "Override Route Dish", "Override Route Item")
        result = generate_intent_day(full_db_conn, "2026-08-31", branch_id, weeks_back=1)
        full_db_conn.commit()

        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post(f"/intent/{result['intentDayId']}/dish/{dish_id}/override", data={
            "_csrf_token": token, "finalQty": "42", "week": "2026-08-31", "day": "2026-08-31", "branchId": branch_id,
        })
        assert resp.status_code == 302
        row = full_db_conn.execute(
            "SELECT finalQty, source FROM IntentDishCount WHERE intentDayId = ? AND dishId = ?",
            (result["intentDayId"], dish_id),
        ).fetchone()
        assert row["finalQty"] == 42.0

    def test_ingredient_qty_update(self, full_app, full_db_conn, branch_id):
        dish_id, item_id = _setup_dish_with_sale(full_db_conn, "Ingredient Route Dish", "Ingredient Route Item")
        result = generate_intent_day(full_db_conn, "2026-08-31", branch_id, weeks_back=1)
        full_db_conn.commit()
        ingredient_row = full_db_conn.execute(
            "SELECT id FROM IntentIngredient WHERE intentDayId = ? AND itemId = ?",
            (result["intentDayId"], item_id),
        ).fetchone()

        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post(f"/intent/{result['intentDayId']}/ingredient/{ingredient_row['id']}/update", data={
            "_csrf_token": token, "qty": "77", "week": "2026-08-31", "day": "2026-08-31", "branchId": branch_id,
        })
        assert resp.status_code == 302
        row = full_db_conn.execute(
            "SELECT qty, source FROM IntentIngredient WHERE id = ?", (ingredient_row["id"],)
        ).fetchone()
        assert row["qty"] == 77.0
        assert row["source"] == "EDITED"

    def test_confirm_day_sets_status_and_confirmer(self, full_app, full_db_conn, branch_id):
        result = generate_intent_day(full_db_conn, "2026-08-31", branch_id, weeks_back=1)
        full_db_conn.commit()

        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post(f"/intent/{result['intentDayId']}/confirm", data={
            "_csrf_token": token, "week": "2026-08-31", "day": "2026-08-31", "branchId": branch_id,
        }, follow_redirects=True)
        assert b"Day confirmed" in resp.data
        row = full_db_conn.execute(
            "SELECT status, confirmedAt, confirmedByUserId FROM IntentDay WHERE id = ?", (result["intentDayId"],)
        ).fetchone()
        assert row["status"] == "CONFIRMED"
        assert row["confirmedAt"] is not None
        assert row["confirmedByUserId"] is not None

    def test_upload_sales_rejects_non_excel_file(self, full_app, full_db_conn, branch_id):
        import io
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/intent/upload-sales", data={
            "_csrf_token": token, "week": "2026-08-31", "branchId": branch_id,
            "files": (io.BytesIO(b"not excel"), "sales.txt"),
        }, content_type="multipart/form-data", follow_redirects=True)
        assert b"not an .xlsx/.xls file" in resp.data

    def test_upload_sales_with_no_files_shows_error(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn)
        token = csrf_token(client)
        resp = client.post("/intent/upload-sales", data={
            "_csrf_token": token, "week": "2026-08-31", "branchId": branch_id,
        }, follow_redirects=True)
        assert b"Choose at least one day-wise sale report" in resp.data


class TestIntentIndexPage:
    def test_index_shows_generated_day_and_dish(self, full_app, full_db_conn, branch_id):
        dish_id, _ = _setup_dish_with_sale(full_db_conn, "Index Page Dish", "Index Page Item")
        generate_intent_day(full_db_conn, "2026-08-31", branch_id, weeks_back=1)
        full_db_conn.commit()

        client = _admin_client(full_app, full_db_conn)
        resp = client.get(f"/intent?week=2026-08-31&day=2026-08-31&branchId={branch_id}")
        assert resp.status_code == 200
        assert b"Index Page Dish" in resp.data

    def test_non_admin_cannot_reach_intent_page(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "MANAGER", branch_id)
        login(client, username, password)
        resp = client.get("/intent")
        assert resp.status_code == 302
