"""Recipe page's "make N kg / N pax" calculator: GET /recipe/<id>/scale
scales one recipe and costs each ingredient (scaled qty x the Item's
purchase price), reusing the same kg/pax conversion Production and
Wastage logging use."""
from __future__ import annotations

import uuid

from tests.conftest import login, make_user


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


def _item(conn, name, unit, price):
    item_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, 'TEST', 1, datetime('now'), datetime('now'))",
        (item_id, name, unit, price),
    )
    return item_id


def _recipe(conn, name, serves_qty, volume_litre, portion_ml, lines):
    """lines: [(item_id | None, qty, raw_name, raw_qty, raw_unit)]"""
    recipe_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO Recipe (id, dishId, name, servesQty, servesVolumeLitre, portionSizeMl, createdAt, updatedAt) "
        "VALUES (?, NULL, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (recipe_id, name, serves_qty, volume_litre, portion_ml),
    )
    for item_id, qty, raw_name, raw_qty, raw_unit in lines:
        conn.execute(
            "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, "
            "matchStatus, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, 'AUTO', datetime('now'))",
            (uuid.uuid4().hex, recipe_id, item_id, qty, raw_name, raw_qty, raw_unit),
        )
    conn.commit()
    return recipe_id


def _sample_recipe(conn):
    """Full batch = 5 kg = 10 pax. A costs 2 x 50, B costs 1 x 30; C has
    no price set; the last line has no Item match at all."""
    a = _item(conn, "Scale Test A", "KG", 50)
    b = _item(conn, "Scale Test B", "KG", 30)
    c = _item(conn, "Scale Test C", "KG", 0)
    return _recipe(conn, "Scale Test Recipe", 10, 5, 500, [
        (a, 2, "a", 2, "kg"), (b, 1, "b", 1, "kg"), (c, 4, "c", 4, "kg"),
        (None, 0, "Curry leaves", 100, "grams"),
    ])


class TestRecipeScaleEndpoint:
    def test_pax_scales_quantities_and_costs_each_ingredient(self, full_app, full_db_conn):
        recipe_id = _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)

        data = client.get(f"/recipe/{recipe_id}/scale?mode=pax&value=5").get_json()
        assert data["multiplier"] == 0.5
        by_name = {l["name"]: l for l in data["lines"]}
        assert by_name["Scale Test A"]["qty"] == 1.0 and by_name["Scale Test A"]["cost"] == 50.0
        assert by_name["Scale Test B"]["qty"] == 0.5 and by_name["Scale Test B"]["cost"] == 15.0
        assert data["totalCost"] == 65.0

    def test_kg_scales_against_the_batch_size(self, full_app, full_db_conn):
        recipe_id = _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)

        data = client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=2.5").get_json()
        assert data["multiplier"] == 0.5, "2.5 kg of a 5 kg batch is half the recipe"
        assert data["totalCost"] == 65.0

        full = client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=5").get_json()
        assert full["multiplier"] == 1.0
        assert full["totalCost"] == 130.0

    def test_kg_and_pax_agree_when_they_describe_the_same_amount(self, full_app, full_db_conn):
        recipe_id = _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)
        by_kg = client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=1").get_json()
        by_pax = client.get(f"/recipe/{recipe_id}/scale?mode=pax&value=2").get_json()
        assert by_kg["totalCost"] == by_pax["totalCost"]

    def test_unpriced_and_unmatched_lines_are_listed_but_left_out_of_the_total(self, full_app, full_db_conn):
        recipe_id = _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)

        data = client.get(f"/recipe/{recipe_id}/scale?mode=pax&value=5").get_json()
        by_name = {l["name"]: l for l in data["lines"]}
        assert by_name["Scale Test C"]["matched"] is True and by_name["Scale Test C"]["cost"] is None
        curry = by_name["Curry leaves"]
        assert curry["matched"] is False and curry["cost"] is None
        assert curry["qty"] == 50.0 and curry["unit"] == "grams"
        assert data["uncostedCount"] == 2, "total is partial, and says by how much"

    def test_bad_input_is_rejected_with_a_message(self, full_app, full_db_conn):
        recipe_id = _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)
        for query in ("mode=pax&value=0", "mode=pax&value=-3", "mode=pax&value=abc",
                      "mode=pax&value=nan", "mode=pax&value=inf", "mode=pax&value=",
                      "mode=litre&value=4", "value=4"):
            resp = client.get(f"/recipe/{recipe_id}/scale?{query}")
            assert resp.status_code == 400, query
            assert resp.get_json()["error"]

    def test_recipe_without_a_kg_yield_cannot_be_scaled_by_kg_but_can_by_pax(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Scale Test D", "KG", 10)
        recipe_id = _recipe(full_db_conn, "Pax Only Recipe", 4, None, None, [(item, 2, "d", 2, "kg")])
        client = _admin_client(full_app, full_db_conn)

        kg = client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=3")
        assert kg.status_code == 400 and "no kg yield" in kg.get_json()["error"]

        pax = client.get(f"/recipe/{recipe_id}/scale?mode=pax&value=2").get_json()
        assert pax["totalCost"] == 10.0  # half of 2 kg x 10

    def test_unknown_recipe_is_404(self, full_app, full_db_conn):
        client = _admin_client(full_app, full_db_conn)
        assert client.get("/recipe/does-not-exist/scale?mode=kg&value=1").status_code == 404

    def test_only_admin_can_use_it(self, full_app, full_db_conn, branch_id):
        recipe_id = _sample_recipe(full_db_conn)
        for role in ("STORE", "KITCHEN"):
            client = full_app.test_client()
            _, username, password = make_user(full_db_conn, role, branch_id)
            login(client, username, password)
            assert client.get(f"/recipe/{recipe_id}/scale?mode=kg&value=1").status_code == 302, role
        assert full_app.test_client().get(f"/recipe/{recipe_id}/scale?mode=kg&value=1").status_code == 302


class TestRecipePage:
    def test_each_recipe_card_gets_the_input_and_shows_the_batch_yield(self, full_app, full_db_conn):
        _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)
        html = client.get("/recipe").get_data(as_text=True)
        assert "js-scale-value" in html
        assert "recipe-scale.js" in html
        assert "5 kg" in html and "10 pax" in html

    def test_full_batch_table_is_still_there_before_anything_is_entered(self, full_app, full_db_conn):
        _sample_recipe(full_db_conn)
        client = _admin_client(full_app, full_db_conn)
        html = client.get("/recipe").get_data(as_text=True)
        assert "Qty for full batch" in html and "Scale Test A" in html
