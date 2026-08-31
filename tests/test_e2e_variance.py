"""Correctness tests for the Produced vs Sold vs Wasted variance
calculation (app.services.wastage_variance.compute_variance): variance
= produced - sold - wasted, in Litres, per recipe. Exact numeric
assertions against a fully controlled scenario -- real Dish/Recipe/
Item rows created in-test, real Production/Wastage log entries, and a
real DishSale row, so the ENTIRE pipeline (recipe text matching, weight
-> ml conversion, dish-sale -> recipe-litres expansion) runs for real.
"""
from __future__ import annotations

from app.dates import date_key_to_db
from app.services.production import create_production
from app.services.wastage import create_wastage
from app.services.wastage_variance import compute_variance


def _setup_recipe(full_db_conn, name: str, portion_size_ml: float, serves_volume_litre: float):
    dept = full_db_conn.execute("SELECT id FROM Department LIMIT 1").fetchone()["id"]
    dish_id = f"dish-{name}"
    full_db_conn.execute(
        "INSERT INTO Dish (id, name, departmentId, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, 'OTHER', 1, datetime('now'), datetime('now'))",
        (dish_id, name, dept),
    )
    recipe_id = f"recipe-{name}"
    full_db_conn.execute(
        "INSERT INTO Recipe (id, dishId, name, servesVolumeLitre, portionSizeMl, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (recipe_id, dish_id, name, serves_volume_litre, portion_size_ml),
    )
    full_db_conn.commit()
    return dish_id, recipe_id


def _log_sale(full_db_conn, dish_id, date_db, qty):
    full_db_conn.execute(
        "INSERT INTO DishSale (id, date, dishId, rawItemName, qty, matchStatus, createdAt) "
        "VALUES (?, ?, ?, 'test', ?, 'AUTO', datetime('now'))",
        (f"sale-{dish_id}-{date_db}", date_db, dish_id, qty),
    )
    full_db_conn.commit()


class TestVarianceFormula:
    def test_exact_produced_sold_wasted_and_variance(self, full_db_conn, branch_id, admin_user_id):
        # portionSizeMl=500 -> qty*500/1000 litres sold per unit sold.
        # servesVolumeLitre=5 -> batch_ml=5000 (nonzero, only needs to be
        # truthy since weight-based produced/wasted math cancels batch_ml
        # out algebraically -- see wastage_variance.py's docstring).
        dish_id, recipe_id = _setup_recipe(full_db_conn, "Test Variance Recipe", 500, 5.0)
        date_key = "2026-08-25"
        date_db = date_key_to_db(date_key)

        # Sold: 10 units * 500ml / 1000 = 5.0 L
        _log_sale(full_db_conn, dish_id, date_db, 10)

        # Produced: 8kg -> 8000ml -> 8.0 L (density=1, KG->1000ml/kg)
        create_production(full_db_conn, admin_user_id, branch_id, date_key, None,
                           "Test Variance Recipe", 8.0, "KG", None, b"x", "p.jpg", "image/jpeg")
        # Wasted: 1kg -> 1.0 L
        create_wastage(full_db_conn, admin_user_id, branch_id, date_key, None,
                        "Test Variance Recipe", 1.0, "KG", None, b"x", "w.jpg", "image/jpeg")

        result = compute_variance(full_db_conn, date_db, branch_id)
        assert result["salesAvailable"] is True
        row = next(r for r in result["rows"] if r["recipeName"] == "Test Variance Recipe")
        assert row["produced"] == 8.0
        assert row["sold"] == 5.0
        assert row["wasted"] == 1.0
        assert row["variance"] == 2.0  # 8 - 5 - 1
        assert row["unit"] == "L"

    def test_no_sale_report_uploaded_yields_sales_available_false(self, full_db_conn, branch_id, admin_user_id):
        dish_id, recipe_id = _setup_recipe(full_db_conn, "No Sales Recipe", 500, 5.0)
        date_key = "2026-08-26"
        date_db = date_key_to_db(date_key)
        create_production(full_db_conn, admin_user_id, branch_id, date_key, None,
                           "No Sales Recipe", 3.0, "KG", None, b"x", "p.jpg", "image/jpeg")

        result = compute_variance(full_db_conn, date_db, branch_id)
        assert result["salesAvailable"] is False
        row = next(r for r in result["rows"] if r["recipeName"] == "No Sales Recipe")
        assert row["sold"] == 0.0
        assert row["produced"] == 3.0
        assert row["variance"] == 3.0

    def test_gm_unit_converts_correctly(self, full_db_conn, branch_id, admin_user_id):
        _setup_recipe(full_db_conn, "Gram Unit Recipe", 500, 5.0)
        date_key = "2026-08-27"
        date_db = date_key_to_db(date_key)
        # 250g -> 250ml -> 0.25 L
        create_wastage(full_db_conn, admin_user_id, branch_id, date_key, None,
                        "Gram Unit Recipe", 250.0, "GM", None, b"x", "w.jpg", "image/jpeg")

        result = compute_variance(full_db_conn, date_db, branch_id)
        row = next(r for r in result["rows"] if r["recipeName"] == "Gram Unit Recipe")
        assert row["wasted"] == 0.25
        assert row["produced"] == 0.0
        assert row["variance"] == -0.25

    def test_unmatched_description_produces_no_row(self, full_db_conn, branch_id, admin_user_id):
        """A production entry whose description doesn't confidently match
        any recipe must not silently create a variance row -- confirmed
        behavior: match_and_scale_entry returns multiplier=None for
        anything below AUTO confidence, and _recipe_litres_from_log skips
        those entirely."""
        date_key = "2026-08-28"
        date_db = date_key_to_db(date_key)
        create_production(full_db_conn, admin_user_id, branch_id, date_key, None,
                           "Totally Unrecognizable Gibberish Zzz", 3.0, "KG", None, b"x", "p.jpg", "image/jpeg")
        result = compute_variance(full_db_conn, date_db, branch_id)
        assert result["rows"] == []

    def test_variance_rows_sorted_by_absolute_variance_descending(self, full_db_conn, branch_id, admin_user_id):
        _setup_recipe(full_db_conn, "Small Variance Recipe", 500, 5.0)
        _setup_recipe(full_db_conn, "Big Variance Recipe", 500, 5.0)
        date_key = "2026-08-29"
        create_production(full_db_conn, admin_user_id, branch_id, date_key, None,
                           "Small Variance Recipe", 1.0, "KG", None, b"x", "p.jpg", "image/jpeg")
        create_production(full_db_conn, admin_user_id, branch_id, date_key, None,
                           "Big Variance Recipe", 20.0, "KG", None, b"x", "p.jpg", "image/jpeg")

        result = compute_variance(full_db_conn, date_key_to_db(date_key), branch_id)
        names = [r["recipeName"] for r in result["rows"]]
        assert names[0] == "Big Variance Recipe"
        assert names[-1] == "Small Variance Recipe"


class TestVarianceEndToEnd:
    def test_wastage_page_shows_variance_to_admin(self, full_app, full_db_conn, branch_id, admin_user_id):
        _setup_recipe(full_db_conn, "Visible Variance Recipe", 500, 5.0)
        date_key = "2026-08-30"
        create_production(full_db_conn, admin_user_id, branch_id, date_key, None,
                           "Visible Variance Recipe", 4.0, "KG", None, b"x", "p.jpg", "image/jpeg")

        from tests.conftest import login, make_user
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "ADMIN", None)
        login(client, username, password)

        resp = client.get(f"/wastage?date={date_key}&branchId={branch_id}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Produced vs Sold vs Wasted" in body
        assert "Visible Variance Recipe" in body

    def test_kitchen_role_does_not_see_variance_card(self, full_app, full_db_conn, branch_id):
        from tests.conftest import login, make_user
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
        login(client, username, password)
        resp = client.get(f"/wastage?date=2026-08-25&branchId={branch_id}")
        assert "Produced vs Sold vs Wasted" not in resp.get_data(as_text=True)
