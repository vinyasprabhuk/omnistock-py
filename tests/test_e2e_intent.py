"""Correctness tests for Intent's dish-count prediction and ingredient
scaling (app.services.intent.generate_intent_day). Exact numeric
assertions against a fully controlled 3-week sale history and a real
recipe, not just "the page renders".
"""
from __future__ import annotations

from app.dates import date_key_to_db, now_db
from app.db import new_id
from app.services.intent import generate_intent_day


def _make_item(conn, name="Test Rice"):
    item_id = new_id()
    conn.execute(
        "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, 'KG', 10, 'TEST', 1, datetime('now'), datetime('now'))",
        (item_id, name),
    )
    conn.commit()
    return item_id


def _make_dish_with_recipe(conn, name, item_id, qty_per_serve, serves_qty=1.0):
    dept = conn.execute("SELECT id FROM Department LIMIT 1").fetchone()["id"]
    dish_id = new_id()
    conn.execute(
        "INSERT INTO Dish (id, name, departmentId, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, 'OTHER', 1, datetime('now'), datetime('now'))",
        (dish_id, name, dept),
    )
    recipe_id = new_id()
    conn.execute(
        "INSERT INTO Recipe (id, dishId, name, servesQty, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
        (recipe_id, dish_id, name, serves_qty),
    )
    conn.execute(
        "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, "
        "matchStatus, createdAt) VALUES (?, ?, ?, ?, 'x', ?, 'KG', 'AUTO', datetime('now'))",
        (new_id(), recipe_id, item_id, qty_per_serve, qty_per_serve),
    )
    conn.commit()
    return dish_id, recipe_id


def _log_sale(conn, dish_id, date_db, qty):
    conn.execute(
        "INSERT INTO DishSale (id, date, dishId, rawItemName, qty, matchStatus, createdAt) "
        "VALUES (?, ?, ?, 'x', ?, 'AUTO', datetime('now'))",
        (new_id(), date_db, dish_id, qty),
    )
    conn.commit()


class TestPredictedQtyIsA3WeekAverage:
    def test_average_of_three_same_weekday_sales(self, full_db_conn, branch_id):
        item_id = _make_item(full_db_conn)
        dish_id, recipe_id = _make_dish_with_recipe(full_db_conn, "Avg Test Dish", item_id, qty_per_serve=2.0)

        # 2026-09-07, 2026-09-14, 2026-09-21, 2026-09-28 are all Mondays.
        # Sell 10, 20, 30 on the three preceding Mondays; predict for the
        # 4th -- average must be exactly (10+20+30)/3 = 20.0.
        for d, qty in (("2026-09-07", 10), ("2026-09-14", 20), ("2026-09-21", 30)):
            _log_sale(full_db_conn, dish_id, date_key_to_db(d), qty)

        result = generate_intent_day(full_db_conn, "2026-09-28", branch_id, weeks_back=3)
        row = full_db_conn.execute(
            "SELECT predictedQty, finalQty, source FROM IntentDishCount WHERE intentDayId = ? AND dishId = ?",
            (result["intentDayId"], dish_id),
        ).fetchone()
        assert row["predictedQty"] == 20.0
        assert row["finalQty"] == 20.0
        assert row["source"] == "AVG"

    def test_missing_week_counts_as_zero_in_the_average(self, full_db_conn, branch_id):
        item_id = _make_item(full_db_conn, "Zero Week Item")
        dish_id, _ = _make_dish_with_recipe(full_db_conn, "Zero Week Dish", item_id, qty_per_serve=1.0)
        # Only ONE Monday has sales (30), but that's still the only distinct
        # sale date in the whole table, so weeks_back=3 only finds 1 history
        # date -- average is 30/1 = 30.0, not diluted by phantom zero weeks
        # that were never a real (dated) history point to begin with.
        _log_sale(full_db_conn, dish_id, date_key_to_db("2026-09-21"), 30)

        result = generate_intent_day(full_db_conn, "2026-09-28", branch_id, weeks_back=3)
        row = full_db_conn.execute(
            "SELECT predictedQty FROM IntentDishCount WHERE intentDayId = ? AND dishId = ?",
            (result["intentDayId"], dish_id),
        ).fetchone()
        assert row["predictedQty"] == 30.0

    def test_manual_override_replaces_average_but_keeps_predicted_for_display(self, full_db_conn, branch_id):
        item_id = _make_item(full_db_conn, "Override Item")
        dish_id, _ = _make_dish_with_recipe(full_db_conn, "Override Dish", item_id, qty_per_serve=1.0)
        _log_sale(full_db_conn, dish_id, date_key_to_db("2026-09-21"), 10)

        result = generate_intent_day(full_db_conn, "2026-09-28", branch_id, weeks_back=3,
                                      dish_overrides={dish_id: 99.0})
        row = full_db_conn.execute(
            "SELECT predictedQty, finalQty, source FROM IntentDishCount WHERE intentDayId = ? AND dishId = ?",
            (result["intentDayId"], dish_id),
        ).fetchone()
        assert row["predictedQty"] == 10.0, "raw average is preserved for display even when overridden"
        assert row["finalQty"] == 99.0
        assert row["source"] == "MANUAL"


class TestIngredientScaling:
    def test_ingredient_qty_scales_by_final_qty_over_serves_qty(self, full_db_conn, branch_id):
        item_id = _make_item(full_db_conn, "Scaling Item")
        # servesQty=5 -> recipe as written feeds 5, needs qty_per_serve=2 of
        # the item per unit served -- i.e. 10 item-units per 5-serve batch.
        dish_id, recipe_id = _make_dish_with_recipe(full_db_conn, "Scaling Dish", item_id,
                                                     qty_per_serve=2.0, serves_qty=5.0)
        _log_sale(full_db_conn, dish_id, date_key_to_db("2026-09-21"), 10)  # sells 10 -> predicted 10

        result = generate_intent_day(full_db_conn, "2026-09-28", branch_id, weeks_back=3)
        # multiplier = finalQty(10) / servesQty(5) = 2.0; ingredient qty =
        # rawQty-per-serve-batch(2.0) * multiplier(2.0) = 4.0
        row = full_db_conn.execute(
            "SELECT qty FROM IntentIngredient WHERE intentDayId = ? AND itemId = ?",
            (result["intentDayId"], item_id),
        ).fetchone()
        assert row["qty"] == 4.0

    def test_regenerating_the_same_day_replaces_not_duplicates(self, full_db_conn, branch_id):
        item_id = _make_item(full_db_conn, "Regen Item")
        dish_id, _ = _make_dish_with_recipe(full_db_conn, "Regen Dish", item_id, qty_per_serve=1.0)
        _log_sale(full_db_conn, dish_id, date_key_to_db("2026-09-21"), 5)

        r1 = generate_intent_day(full_db_conn, "2026-09-28", branch_id, weeks_back=3)
        r2 = generate_intent_day(full_db_conn, "2026-09-28", branch_id, weeks_back=3)
        assert r1["intentDayId"] == r2["intentDayId"]
        count = full_db_conn.execute(
            "SELECT COUNT(*) FROM IntentDishCount WHERE intentDayId = ?", (r1["intentDayId"],)
        ).fetchone()[0]
        assert count == 1, "regenerating must replace rows, not accumulate duplicates"


class TestIntentEndToEnd:
    def test_intent_page_shows_predicted_qty_to_admin(self, full_app, full_db_conn, branch_id):
        item_id = _make_item(full_db_conn, "Page Item")
        dish_id, _ = _make_dish_with_recipe(full_db_conn, "Page Dish", item_id, qty_per_serve=1.0)
        _log_sale(full_db_conn, dish_id, date_key_to_db("2026-09-21"), 7)

        from tests.conftest import login, make_user
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "ADMIN", None)
        login(client, username, password)
        token = client.get("/api/csrf-token").get_json()["csrfToken"]

        resp = client.post("/intent/generate", data={
            "_csrf_token": token, "date": "2026-09-28", "week": "2026-09-28", "branchId": branch_id,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Page Dish" in resp.data
