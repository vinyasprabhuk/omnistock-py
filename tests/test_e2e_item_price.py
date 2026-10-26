"""Admin > Items: each item's purchase price can be changed."""
from __future__ import annotations

import uuid

from tests.conftest import csrf_token, login, make_user


def _admin(full_app, conn):
    client = full_app.test_client()
    _, username, password = make_user(conn, "ADMIN", None)
    login(client, username, password)
    return client


def _item(conn, name, price=10, unit="Kg"):
    item_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, 'TEST', 1, datetime('now'), datetime('now'))", (item_id, name, unit, price),
    )
    conn.commit()
    return item_id


def _price(conn, item_id):
    return conn.execute("SELECT purchasePrice FROM Item WHERE id = ?", (item_id,)).fetchone()["purchasePrice"]


def _post(client, item_id, price, follow=True):
    return client.post(f"/admin/items/{item_id}/price", data={"_csrf_token": csrf_token(client), "price": price},
                       follow_redirects=follow)


class TestSetItemPrice:
    def test_admin_changes_the_price(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Price Test Hing", 1554)
        html = _post(_admin(full_app, full_db_conn), item, "1000").get_data(as_text=True)
        assert "Price Test Hing: price set to 1000" in html
        assert _price(full_db_conn, item) == 1000

    def test_decimals_and_zero_are_allowed(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Price Test Decimal", 5)
        client = _admin(full_app, full_db_conn)
        _post(client, item, "22.5")
        assert _price(full_db_conn, item) == 22.5
        _post(client, item, "0")
        assert _price(full_db_conn, item) == 0

    def test_bad_values_are_refused_and_the_price_is_kept(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Price Test Bad", 77)
        client = _admin(full_app, full_db_conn)
        for bad in ("", "abc", "-1", "nan", "inf", "99999999999"):
            html = _post(client, item, bad).get_data(as_text=True)
            assert "price set to" not in html, bad
        assert _price(full_db_conn, item) == 77

    def test_unknown_item_is_reported(self, full_app, full_db_conn):
        html = _post(_admin(full_app, full_db_conn), "nope", "5").get_data(as_text=True)
        assert "Item not found" in html

    def test_only_admin_can_change_prices(self, full_app, full_db_conn, branch_id):
        item = _item(full_db_conn, "Price Test Locked", 50)
        for role in ("STORE", "KITCHEN"):
            client = full_app.test_client()
            _, username, password = make_user(full_db_conn, role, branch_id)
            login(client, username, password)
            resp = client.post(f"/admin/items/{item}/price", data={"_csrf_token": csrf_token(client), "price": "1"})
            assert resp.status_code in (302, 403), role
        assert _price(full_db_conn, item) == 50

    def test_page_shows_an_editable_price_for_each_item(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Price Test Shown", 123.4)
        html = _admin(full_app, full_db_conn).get("/admin/items").get_data(as_text=True)
        assert f"/admin/items/{item}/price" in html and 'value="123.40"' in html

    def test_recipe_cost_follows_the_new_price(self, full_app, full_db_conn):
        item = _item(full_db_conn, "Price Test Costed", 100)
        recipe_id = uuid.uuid4().hex
        full_db_conn.execute(
            "INSERT INTO Recipe (id, dishId, name, servesQty, servesVolumeLitre, portionSizeMl, createdAt, updatedAt) "
            "VALUES (?, NULL, 'Price Test Recipe', 10, 1, NULL, datetime('now'), datetime('now'))", (recipe_id,))
        full_db_conn.execute(
            "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, matchStatus, createdAt) "
            "VALUES (?, ?, ?, 0.5, 'x', 0.5, 'kg', 'AUTO', datetime('now'))", (uuid.uuid4().hex, recipe_id, item))
        full_db_conn.commit()
        client = _admin(full_app, full_db_conn)
        assert client.get(f"/recipe/{recipe_id}/scale?mode=pax&value=10").get_json()["totalCost"] == 50
        _post(client, item, "300")
        assert client.get(f"/recipe/{recipe_id}/scale?mode=pax&value=10").get_json()["totalCost"] == 150
