"""Recipe page: "Re-match unmatched lines" (after adding an item/alias) and
"Full batch makes N kg" for recipes whose document gave only a piece count."""
from __future__ import annotations

import uuid

from app.services.admin import add_item_alias
from app.services.recipe_loader import rematch_unmatched_lines
from tests.conftest import csrf_token, login, make_user


def _item(conn, name, unit="Kg", price=10):
    item_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, 'TEST', 1, datetime('now'), datetime('now'))", (item_id, name, unit, price),
    )
    return item_id


def _recipe(conn, name, lines, serves_qty=None, litres=None):
    """lines: [(raw_name, raw_value, raw_unit, item_id | None)]"""
    recipe_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO Recipe (id, dishId, name, servesQty, servesVolumeLitre, portionSizeMl, createdAt, updatedAt) "
        "VALUES (?, NULL, ?, ?, ?, NULL, datetime('now'), datetime('now'))", (recipe_id, name, serves_qty, litres),
    )
    ids = []
    for raw_name, value, unit, item_id in lines:
        line_id = uuid.uuid4().hex
        ids.append(line_id)
        conn.execute(
            "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, "
            "matchStatus, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (line_id, recipe_id, item_id, value, raw_name, value, unit, "AUTO" if item_id else "MANUAL"),
        )
    conn.commit()
    return recipe_id, ids


def _line(conn, line_id):
    return conn.execute("SELECT itemId, qty, matchStatus FROM RecipeLine WHERE id = ?", (line_id,)).fetchone()


def _admin(full_app, conn):
    client = full_app.test_client()
    _, username, password = make_user(conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestRematch:
    def test_alias_added_later_links_the_line_and_converts_the_unit(self, full_db_conn):
        item = _item(full_db_conn, "Rematch Urid Dhal", "Kg")
        _, (line_id,) = _recipe(full_db_conn, "Rematch Recipe A", [("Rematch Urad Pulse", 300, "grams", None)])
        assert _line(full_db_conn, line_id)["itemId"] is None

        add_item_alias(full_db_conn, item, "Rematch Urad Pulse")
        result = rematch_unmatched_lines(full_db_conn)

        assert result["linked"] >= 1
        row = _line(full_db_conn, line_id)
        assert row["itemId"] == item and row["matchStatus"] == "AUTO"
        assert abs(row["qty"] - 0.3) < 1e-9, "300 g stored as 0.3 of a Kg item"

    def test_a_line_with_no_confident_match_is_left_alone(self, full_db_conn):
        _item(full_db_conn, "Rematch Something Else", "Kg")
        _, (line_id,) = _recipe(full_db_conn, "Rematch Recipe B", [("Zzqx Nonexistent Spice", 5, "grams", None)])
        rematch_unmatched_lines(full_db_conn)
        assert _line(full_db_conn, line_id)["itemId"] is None

    def test_a_unit_that_cannot_convert_stays_unmatched(self, full_db_conn):
        item = _item(full_db_conn, "Rematch Garlic Bulb", "Kg")
        add_item_alias(full_db_conn, item, "Rematch Garlic Cloves")
        _, (line_id,) = _recipe(full_db_conn, "Rematch Recipe C", [("Rematch Garlic Cloves", 10, "cloves", None)])
        rematch_unmatched_lines(full_db_conn)
        assert _line(full_db_conn, line_id)["itemId"] is None

    def test_lines_that_already_have_an_item_are_never_changed(self, full_db_conn):
        original = _item(full_db_conn, "Rematch Original Item", "Kg")
        other = _item(full_db_conn, "Rematch Better Looking Item", "Kg")
        add_item_alias(full_db_conn, other, "Rematch Original Item")
        _, (line_id,) = _recipe(full_db_conn, "Rematch Recipe D", [("Rematch Original Item", 2, "kg", original)])
        rematch_unmatched_lines(full_db_conn)
        row = _line(full_db_conn, line_id)
        assert row["itemId"] == original and row["qty"] == 2

    def test_button_runs_it_and_reports_counts(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Rematch Page Item", "Litre")
        add_item_alias(full_db_conn, item, "Rematch Page Oil")
        _, (line_id,) = _recipe(full_db_conn, "Rematch Recipe E", [("Rematch Page Oil", 500, "ml", None)])
        client = _admin(full_app, full_db_conn)
        html = client.post("/recipe/rematch", data={"_csrf_token": csrf_token(client)},
                           follow_redirects=True).get_data(as_text=True)
        assert "Re-matched" in html and "unmatched recipe lines" in html
        assert _line(full_db_conn, line_id)["itemId"] == item

    def test_kitchen_user_cannot_run_it(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        resp = client.post("/recipe/rematch", data={"_csrf_token": csrf_token(client)})
        assert resp.status_code in (302, 403)


class TestBatchSize:
    def test_saving_a_batch_size_enables_kg_scaling(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Yield Test Flour", "Kg", 50)
        recipe_id, _ = _recipe(full_db_conn, "Yield Test Recipe", [("Yield Test Flour", 2, "kg", item)], serves_qty=20)
        client = _admin(full_app, full_db_conn)
        assert client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=1").status_code == 400

        html = client.post(f"/recipe/{recipe_id}/yield", data={"_csrf_token": csrf_token(client), "kg": "4"},
                           follow_redirects=True).get_data(as_text=True)
        assert "Batch size saved: 4 kg" in html

        data = client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=2").get_json()
        assert data["multiplier"] == 0.5 and data["totalCost"] == 50.0  # half of 2 kg x 50

    def test_bad_values_are_refused_and_nothing_changes(self, full_app, full_db_conn):
        recipe_id, _ = _recipe(full_db_conn, "Yield Test Bad Input", [], serves_qty=5)
        client = _admin(full_app, full_db_conn)
        for bad in ("", "abc", "0", "-2", "nan", "inf", "5000"):
            client.post(f"/recipe/{recipe_id}/yield", data={"_csrf_token": csrf_token(client), "kg": bad})
        row = full_db_conn.execute("SELECT servesVolumeLitre FROM Recipe WHERE id = ?", (recipe_id,)).fetchone()
        assert row["servesVolumeLitre"] is None

    def test_unknown_recipe_is_reported(self, full_app, full_db_conn):
        client = _admin(full_app, full_db_conn)
        html = client.post("/recipe/nope/yield", data={"_csrf_token": csrf_token(client), "kg": "2"},
                           follow_redirects=True).get_data(as_text=True)
        assert "Recipe not found" in html

    def test_form_shows_only_on_recipes_without_a_kg_yield(self, full_app, full_db_conn):
        no_kg, _ = _recipe(full_db_conn, "Yield Test No Kg", [], serves_qty=8)
        has_kg, _ = _recipe(full_db_conn, "Yield Test Has Kg", [], serves_qty=8, litres=2)
        html = _admin(full_app, full_db_conn).get("/recipe").get_data(as_text=True)
        assert f"/recipe/{no_kg}/yield" in html
        assert f"/recipe/{has_kg}/yield" not in html


class TestUnitWeights:
    """Counted/spooned units convert via the kitchen's per-item weights."""

    def test_weights_convert_to_kg(self):
        from app.services.recipe_loader import _convert_qty
        assert abs(_convert_qty(6, "pieces", "Kg", "Green chilly") - 0.030) < 1e-9
        assert abs(_convert_qty(10, "cloves", "Kg", "Garlic") - 0.050) < 1e-9
        assert abs(_convert_qty(3, "coconuts", "Kg", "Coconut") - 0.850) < 1e-9
        assert abs(_convert_qty(2, "pieces", "Kg", "Drumsticks") - 0.240) < 1e-9
        assert abs(_convert_qty(2, "pieces", "Kg", "Capsicum") - 0.400) < 1e-9
        assert abs(_convert_qty(1, "pieces", "Kg", "Raw banana") - 0.120) < 1e-9
        assert abs(_convert_qty(3, "spoons", "Kg", "Chilly Powder") - 0.090) < 1e-9
        assert abs(_convert_qty(1.5, "spoons", "Kg", "Turmeric Powder") - 0.045) < 1e-9
        assert abs(_convert_qty(3, "spoons", "Kg", "Pepper") - 0.060) < 1e-9

    def test_unknown_item_or_unit_is_still_not_guessed(self):
        from app.services.recipe_loader import _convert_qty
        assert _convert_qty(5, "pieces", "Kg", "Cashew") is None          # no weight supplied
        assert _convert_qty(5, "spoons", "Kg", "Green chilly") is None    # no spoon weight for it
        assert _convert_qty(5, "bunches", "Kg", "Garlic") is None
        assert _convert_qty(5, "pieces", "Kg") is None                    # no item name

    def test_ordinary_conversions_are_unchanged(self):
        from app.services.recipe_loader import _convert_qty
        assert _convert_qty(250, "grams", "Kg", "Garlic") == 0.25
        assert _convert_qty(500, "ml", "Litre", "Curd") == 0.5
        assert _convert_qty(4, "pieces", "Piece", "Anything") == 4

    def test_rematch_links_a_counted_line_using_the_weight(self, full_db_conn):
        item = _item(full_db_conn, "Green chilly", "Kg")
        add_item_alias(full_db_conn, item, "Unitweight Green Chillies")
        _, (line_id,) = _recipe(full_db_conn, "Unit Weight Recipe",
                                [("Unitweight Green Chillies", 6, "pieces", None)])
        rematch_unmatched_lines(full_db_conn)
        row = _line(full_db_conn, line_id)
        assert row["itemId"] == item and abs(row["qty"] - 0.030) < 1e-9
