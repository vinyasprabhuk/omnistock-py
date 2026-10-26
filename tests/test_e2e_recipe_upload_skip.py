"""Recipe upload is add-only: a recipe whose name already exists (same name,
or a close automatic match) is skipped and left untouched; only genuinely new
recipes are loaded."""
from __future__ import annotations

import io
import uuid
import zipfile
from xml.sax.saxutils import escape

from app.services.recipe_loader import load_recipes_from_docx
from tests.conftest import csrf_token, login, make_user


def _docx_bytes(recipes) -> bytes:
    """recipes: [(name, pax, litres, [(ingredient, qty_text)])] in the layout
    parse_recipe_docx reads (Recipe Name marker, then a 2-column table)."""
    def p(text):
        return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'

    body = ""
    for name, pax, litres, rows in recipes:
        body += p("Recipe Name") + p(name) + p("Category") + p("Test") + p("Serving Size")
        body += p(f"Serves: {pax} pax ({litres} litres)") + p("Portion Size: 100 ml")
        body += p("Ingredients List & Steps") + "<w:tbl>"
        for ing, qty in rows:
            body += f"<w:tr><w:tc>{p(ing)}</w:tc><w:tc>{p(qty)}</w:tc></w:tr>"
        body += "</w:tbl>"
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def _write(tmp_path, recipes) -> str:
    path = tmp_path / f"{uuid.uuid4().hex}.docx"
    path.write_bytes(_docx_bytes(recipes))
    return str(path)


def _seed_recipe(conn, name, ingredient="Seed Ingredient", qty=1.0):
    recipe_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO Recipe (id, dishId, name, servesQty, servesVolumeLitre, portionSizeMl, createdAt, updatedAt) "
        "VALUES (?, NULL, ?, 10, 1, 100, datetime('now'), datetime('now'))", (recipe_id, name),
    )
    conn.execute(
        "INSERT INTO RecipeLine (id, recipeId, itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, "
        "matchStatus, createdAt) VALUES (?, ?, NULL, ?, ?, ?, 'kg', 'AUTO', datetime('now'))",
        (uuid.uuid4().hex, recipe_id, qty, ingredient, qty),
    )
    conn.commit()
    return recipe_id


def _recipe_names(conn):
    return {r["name"] for r in conn.execute("SELECT name FROM Recipe")}


class TestUploadSkipsExisting:
    def test_new_recipe_is_loaded(self, full_db_conn, tmp_path):
        summary = load_recipes_from_docx(full_db_conn, _write(tmp_path, [
            ("Skip Test Brand New Dish", 10, 1, [("Skip Test Flour", "500 grams")]),
        ]))
        assert summary["recipesLoaded"] == 1 and summary["recipesSkipped"] == []
        assert "Skip Test Brand New Dish" in _recipe_names(full_db_conn)

    def test_same_name_is_skipped_and_left_untouched(self, full_db_conn, tmp_path):
        recipe_id = _seed_recipe(full_db_conn, "Skip Test Existing Dish", ingredient="Original Line", qty=1.0)
        summary = load_recipes_from_docx(full_db_conn, _write(tmp_path, [
            ("skip test existing dish", 50, 9, [("Replacement Line", "9 kg")]),  # same name, other case
        ]))
        assert summary["recipesLoaded"] == 0
        assert summary["recipesSkipped"] == [("skip test existing dish", "Skip Test Existing Dish")]
        lines = full_db_conn.execute(
            "SELECT rawIngredientName FROM RecipeLine WHERE recipeId = ?", (recipe_id,)).fetchall()
        assert [l["rawIngredientName"] for l in lines] == ["Original Line"]
        recipe = full_db_conn.execute("SELECT servesQty, servesVolumeLitre FROM Recipe WHERE id = ?", (recipe_id,)).fetchone()
        assert (recipe["servesQty"], recipe["servesVolumeLitre"]) == (10, 1)
        assert full_db_conn.execute("SELECT COUNT(*) c FROM Recipe WHERE lower(name) = 'skip test existing dish'").fetchone()["c"] == 1

    def test_close_name_match_is_skipped_too(self, full_db_conn, tmp_path):
        _seed_recipe(full_db_conn, "Tamilnadu Skipsambar")
        summary = load_recipes_from_docx(full_db_conn, _write(tmp_path, [
            ("Tamil Nadu Skipsambar", 90, 9, [("Anything", "1 kg")]),
        ]))
        assert summary["recipesLoaded"] == 0
        assert summary["recipesSkipped"] == [("Tamil Nadu Skipsambar", "Tamilnadu Skipsambar")]

    def test_only_the_clashing_recipes_are_skipped_from_a_mixed_file(self, full_db_conn, tmp_path):
        _seed_recipe(full_db_conn, "Skip Test Mixed Old")
        summary = load_recipes_from_docx(full_db_conn, _write(tmp_path, [
            ("Skip Test Mixed Old", 10, 1, [("X", "1 kg")]),
            ("Wholly Different Pongal Special", 10, 1, [("Y", "2 kg")]),
        ]))
        assert summary["recipesLoaded"] == 1
        assert [s[0] for s in summary["recipesSkipped"]] == ["Skip Test Mixed Old"]
        assert "Wholly Different Pongal Special" in _recipe_names(full_db_conn)

    def test_uploading_the_same_file_twice_adds_nothing_the_second_time(self, full_db_conn, tmp_path):
        path = _write(tmp_path, [("Skip Test Twice Dish", 10, 1, [("Z", "1 kg")])])
        assert load_recipes_from_docx(full_db_conn, path)["recipesLoaded"] == 1
        second = load_recipes_from_docx(full_db_conn, path)
        assert second["recipesLoaded"] == 0 and len(second["recipesSkipped"]) == 1
        assert full_db_conn.execute("SELECT COUNT(*) c FROM Recipe WHERE name = 'Skip Test Twice Dish'").fetchone()["c"] == 1

    def test_a_name_repeated_inside_one_file_loads_once(self, full_db_conn, tmp_path):
        summary = load_recipes_from_docx(full_db_conn, _write(tmp_path, [
            ("Skip Test Repeated Dish", 10, 1, [("A", "1 kg")]),
            ("Skip Test Repeated Dish", 10, 1, [("B", "2 kg")]),
        ]))
        assert summary["recipesLoaded"] == 1
        assert summary["recipesSkipped"] == [("Skip Test Repeated Dish", "repeated in this file")]

    def test_new_recipes_in_one_file_never_skip_each_other(self, full_db_conn, tmp_path):
        summary = load_recipes_from_docx(full_db_conn, _write(tmp_path, [
            ("Ghee Podi Thatte Idli", 1, 1, [("A", "1 kg")]),
            ("Ghee Podi Mini Idli", 1, 1, [("B", "1 kg")]),
        ]))
        assert summary["recipesLoaded"] == 2 and summary["recipesSkipped"] == []


class TestUploadMessage:
    def test_flash_names_what_was_skipped(self, full_app, full_db_conn, tmp_path):
        _seed_recipe(full_db_conn, "Skip Test Flash Dish")
        _, username, password = make_user(full_db_conn, "ADMIN", None)
        client = full_app.test_client()
        login(client, username, password)
        data = _docx_bytes([
            ("Skip Test Flash Dish", 10, 1, [("Q", "1 kg")]),
            ("Skip Test Flash Newcomer", 10, 1, [("R", "1 kg")]),
        ])
        resp = client.post("/recipe/upload", data={
            "_csrf_token": csrf_token(client), "file": (io.BytesIO(data), "recipes.docx"),
        }, content_type="multipart/form-data", follow_redirects=True)
        html = resp.get_data(as_text=True)
        assert "Loaded 1 new recipes" in html
        assert "Skipped 1 that already exist" in html and "Skip Test Flash Dish (already have Skip Test Flash Dish)" in html
