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
        assert _convert_qty(5, "pieces", "Kg", "Paneer") is None          # no weight supplied
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


class TestMoreUnitWeights:
    def test_new_weights(self):
        from app.services.recipe_loader import _convert_qty
        assert abs(_convert_qty(10, "pieces", "Kg", "Red Chilli") - 0.050) < 1e-9
        assert abs(_convert_qty(10, "pieces", "Kg", "Cashew") - 0.040) < 1e-9
        assert abs(_convert_qty(1, "nos", "Kg", "Cauliflower") - 0.300) < 1e-9
        assert abs(_convert_qty(5, "bunches", "Kg", "Coriander leaves") - 0.400) < 1e-9
        assert abs(_convert_qty(10, "pieces", "Kg", "Banana") - 1.180) < 1e-9
        assert abs(_convert_qty(3, "nos", "Kg", "Coconut") - 0.850) < 1e-9

    def test_tamarind_extract_ml_is_a_fifth_of_tamarind_by_weight(self):
        from app.services.recipe_loader import _convert_qty
        assert abs(_convert_qty(250, "ml", "Kg", "Tamarind") - 0.050) < 1e-9
        assert _convert_qty(100, "grams", "Kg", "Tamarind") == 0.1, "grams are untouched"
        assert _convert_qty(250, "ml", "Kg", "Curd") == 0.25, "other items keep 1 ml = 1 g"


class TestSubRecipeExpansion:
    def _batter(self, conn):
        rice = _item(conn, "Expand Rice", "Kg", 40)
        dal = _item(conn, "Expand Dal", "Kg", 100)
        recipe_id, _ = _recipe(conn, "Expand Batter", [
            ("Expand Rice", 1.0, "kg", rice), ("Expand Dal", 0.3, "kg", dal), ("Mystery Spice", 10, "grams", None),
        ], serves_qty=80, litres=4)
        return rice, dal, recipe_id

    def test_a_line_naming_another_recipe_becomes_its_ingredients_scaled(self, full_db_conn):
        rice, dal, _ = self._batter(full_db_conn)
        parent, _ = _recipe(full_db_conn, "Expand Parent", [("Expand Batter", 400, "grams", None)])

        result = rematch_unmatched_lines(full_db_conn)

        assert result["expanded"] == 1
        lines = {l["rawIngredientName"]: l for l in full_db_conn.execute(
            "SELECT * FROM RecipeLine WHERE recipeId = ?", (parent,))}
        assert "Expand Batter" not in lines, "the text line is replaced"
        assert lines["Expand Rice"]["itemId"] == rice and abs(lines["Expand Rice"]["qty"] - 0.1) < 1e-9
        assert lines["Expand Dal"]["itemId"] == dal and abs(lines["Expand Dal"]["qty"] - 0.03) < 1e-9
        assert lines["Mystery Spice"]["itemId"] is None and abs(lines["Mystery Spice"]["rawQtyValue"] - 1.0) < 1e-9

    def test_the_source_recipe_is_not_changed(self, full_db_conn):
        _, _, batter = self._batter(full_db_conn)
        _recipe(full_db_conn, "Expand Parent B", [("Expand Batter", 400, "grams", None)])
        rematch_unmatched_lines(full_db_conn)
        assert full_db_conn.execute("SELECT COUNT(*) c FROM RecipeLine WHERE recipeId = ?", (batter,)).fetchone()["c"] == 3

    def test_alias_spelling_points_at_the_same_recipe(self, full_db_conn):
        full_db_conn.execute("UPDATE Recipe SET name = 'Idli Batter' WHERE name = 'Idli Batter' ")  # no-op
        rice = _item(full_db_conn, "Mini Rice", "Kg", 40)
        _recipe(full_db_conn, "Idli Batter", [("Mini Rice", 1.0, "kg", rice)], serves_qty=80, litres=4)
        parent, _ = _recipe(full_db_conn, "Expand Mini Parent", [("Mini idli batter", 10, "grams", None)])
        rematch_unmatched_lines(full_db_conn)
        line = full_db_conn.execute("SELECT itemId, qty FROM RecipeLine WHERE recipeId = ?", (parent,)).fetchone()
        assert line["itemId"] == rice and abs(line["qty"] - 0.0025) < 1e-9

    def test_no_batch_size_or_a_count_unit_means_no_expansion(self, full_db_conn):
        rice = _item(full_db_conn, "Expand Rice 2", "Kg", 40)
        _recipe(full_db_conn, "Expand No Yield", [("Expand Rice 2", 1.0, "kg", rice)])  # no yield
        _recipe(full_db_conn, "Expand Has Yield", [("Expand Rice 2", 1.0, "kg", rice)], litres=4)
        p1, _ = _recipe(full_db_conn, "Expand Parent C", [("Expand No Yield", 400, "grams", None)])
        p2, _ = _recipe(full_db_conn, "Expand Parent D", [("Expand Has Yield", 3, "pieces", None)])
        result = rematch_unmatched_lines(full_db_conn)
        assert result["expanded"] == 0
        for parent, name in ((p1, "Expand No Yield"), (p2, "Expand Has Yield")):
            assert [l["rawIngredientName"] for l in full_db_conn.execute(
                "SELECT rawIngredientName FROM RecipeLine WHERE recipeId = ?", (parent,))] == [name]

    def test_a_recipe_never_expands_into_itself(self, full_db_conn):
        rice = _item(full_db_conn, "Expand Rice 3", "Kg", 40)
        rid, _ = _recipe(full_db_conn, "Expand Selfie", [("Expand Rice 3", 1.0, "kg", rice), ("Expand Selfie", 100, "grams", None)], litres=4)
        assert rematch_unmatched_lines(full_db_conn)["expanded"] == 0
        assert full_db_conn.execute("SELECT COUNT(*) c FROM RecipeLine WHERE recipeId = ?", (rid,)).fetchone()["c"] == 2


class TestMovingOffUnpricedItems:
    def test_line_on_a_free_item_moves_to_the_priced_item_its_name_now_matches(self, full_db_conn):
        wrong = _item(full_db_conn, "Free Boondhi", "Kg", price=0)
        right = _item(full_db_conn, "Real Hing Powder", "Kg", price=1500)
        add_item_alias(full_db_conn, right, "Hingu Moved")           # the corrected alias
        _, (line_id,) = _recipe(full_db_conn, "Moved Recipe A", [("Hingu Moved", 10, "grams", wrong)])

        result = rematch_unmatched_lines(full_db_conn)

        assert result["moved"] >= 1
        row = _line(full_db_conn, line_id)
        assert row["itemId"] == right and abs(row["qty"] - 0.01) < 1e-9

    def test_a_free_item_with_no_better_match_is_left_alone(self, full_db_conn):
        free = _item(full_db_conn, "Moved Free Only", "Kg", price=0)
        _, (line_id,) = _recipe(full_db_conn, "Moved Recipe B", [("Moved Free Only", 2, "kg", free)])
        rematch_unmatched_lines(full_db_conn)
        row = _line(full_db_conn, line_id)
        assert row["itemId"] == free and row["qty"] == 2

    def test_never_moves_onto_another_unpriced_item(self, full_db_conn):
        wrong = _item(full_db_conn, "Moved Wrong Free", "Kg", price=0)
        other_free = _item(full_db_conn, "Moved Other Free", "Kg", price=0)
        add_item_alias(full_db_conn, other_free, "Moved Target Name")
        _, (line_id,) = _recipe(full_db_conn, "Moved Recipe C", [("Moved Target Name", 1, "kg", wrong)])
        rematch_unmatched_lines(full_db_conn)
        assert _line(full_db_conn, line_id)["itemId"] == wrong

    def test_a_priced_item_is_never_touched(self, full_db_conn):
        priced = _item(full_db_conn, "Moved Priced Keeps", "Kg", price=40)
        better = _item(full_db_conn, "Moved Better Priced", "Kg", price=50)
        add_item_alias(full_db_conn, better, "Moved Priced Keeps")
        _, (line_id,) = _recipe(full_db_conn, "Moved Recipe D", [("Moved Priced Keeps", 1, "kg", priced)])
        rematch_unmatched_lines(full_db_conn)
        assert _line(full_db_conn, line_id)["itemId"] == priced

    def test_flash_mentions_moved_lines(self, full_app, full_db_conn):
        wrong = _item(full_db_conn, "Flash Free Item", "Kg", price=0)
        right = _item(full_db_conn, "Flash Real Item", "Kg", price=90)
        add_item_alias(full_db_conn, right, "Flash Moved Spice")
        _recipe(full_db_conn, "Moved Recipe E", [("Flash Moved Spice", 5, "grams", wrong)])
        client = _admin(full_app, full_db_conn)
        html = client.post("/recipe/rematch", data={"_csrf_token": csrf_token(client)},
                           follow_redirects=True).get_data(as_text=True)
        assert "on an item with no price moved to the priced item" in html
