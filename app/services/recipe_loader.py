"""
Loads parsed recipe.docx recipes into Dish/Recipe/RecipeLine, matching each
ingredient line against Item Master via the existing item matcher and
converting the recipe doc's raw unit (grams/ml/kg/pieces) into whatever unit
the matched Item actually uses. A line whose ingredient has no confident
Item Master match keeps itemId NULL and its raw name/qty/unit intact, so it
can be resolved later (see matchStatus) once the missing item is added --
nothing about it is guessed at import time.
"""
from __future__ import annotations

import sqlite3

from app.db import new_id
from app.dates import now_db
from app.parsing.recipe_docx import ParsedRecipe, parse_recipe_docx
from app.services.dish_classify import guess_menu_group
from app.services.match_item import match_item

# Recipes that are themselves sellable dishes (confirmed against the real
# POS sale report -- see the "add it" conversation this was built from).
# Every other recipe in the doc is an accompaniment / sub-recipe only,
# referenced by intent_rules.py rather than sold on its own.
DISH_RECIPES: dict[str, str] = {
    "Kara Bath": "PONGAL_KARABATH",
    "Ghee Pongal": "PONGAL_KARABATH",
    "Kesari": "OTHER",
    "Curd Rice": "VARIETY_RICE",
    "Sambar Rice": "VARIETY_RICE",
}

_WEIGHT = {"g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0}
_VOLUME = {"ml": 1.0, "l": 1000.0, "litre": 1000.0, "liter": 1000.0, "ltr": 1000.0}
_COUNT = {"piece": 1.0, "pieces": 1.0, "pcs": 1.0, "pc": 1.0, "nos": 1.0, "no": 1.0, "": 1.0}


def _convert_qty(value: float, raw_unit: str, target_unit: str) -> float | None:
    """Converts a recipe-doc quantity (in raw_unit) into target_unit's scale.
    Returns None if the two units aren't in the same family (weight/volume/count).

    The recipe doc measures liquids like oil, milk and curd in grams even
    though Item Master tracks them in Litres -- a weight/volume mismatch, not
    a bad match. Falls back to a 1 gram = 1 ml density assumption in that
    case (accurate for milk/curd, a reasonable approximation for oil) rather
    than leaving those lines unmatched."""
    raw_unit = raw_unit.lower()
    target = target_unit.lower()
    if raw_unit in _WEIGHT and target == "kg":
        return value * _WEIGHT[raw_unit] / 1000.0
    if raw_unit in _VOLUME and target == "litre":
        return value * _VOLUME[raw_unit] / 1000.0
    if raw_unit in _COUNT and target in ("piece", "pieces"):
        return value
    if raw_unit in _WEIGHT and target == "litre":
        return value * _WEIGHT[raw_unit] / 1000.0
    if raw_unit in _VOLUME and target == "kg":
        return value * _VOLUME[raw_unit] / 1000.0
    return None


def load_recipes_from_docx(conn: sqlite3.Connection, docx_path: str, department_id: str) -> dict:
    """department_id is used for every newly-created Dish (see DISH_RECIPES) --
    all 5 land under the same kitchen department for now; correct per-dish
    later via the Recipe tab once it exists."""
    recipes = parse_recipe_docx(docx_path)
    summary = {"recipesLoaded": 0, "linesMatched": 0, "linesUnmatched": []}

    for r in recipes:
        r: ParsedRecipe
        dish_id = None
        if r["name"] in DISH_RECIPES:
            existing = conn.execute("SELECT id FROM Dish WHERE name = ?", (r["name"],)).fetchone()
            if existing:
                dish_id = existing["id"]
            else:
                dish_id = new_id()
                ts = now_db()
                menu_group = guess_menu_group("", r["name"])
                conn.execute(
                    "INSERT INTO Dish (id, name, departmentId, category, menuGroup, active, createdAt, updatedAt) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                    (dish_id, r["name"], department_id, DISH_RECIPES[r["name"]], menu_group, ts, ts),
                )

        recipe_id = new_id()
        ts = now_db()
        conn.execute(
            "INSERT INTO Recipe (id, dishId, name, servesQty, servesVolumeLitre, portionSizeMl, createdAt, updatedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (recipe_id, dish_id, r["name"], r["servesQty"], r["servesVolumeLitre"], r["portionSizeMl"], ts, ts),
        )
        summary["recipesLoaded"] += 1

        for ing in r["ingredients"]:
            match = match_item(conn, ing["ingredientName"])
            item_id = None
            converted_qty = ing["qtyValue"]
            if match["status"] == "AUTO" and match["matchedItemId"]:
                item_row = conn.execute(
                    "SELECT unit FROM Item WHERE id = ?", (match["matchedItemId"],)
                ).fetchone()
                converted = _convert_qty(ing["qtyValue"], ing["qtyUnit"], item_row["unit"])
                if converted is not None:
                    item_id = match["matchedItemId"]
                    converted_qty = converted
                    summary["linesMatched"] += 1
                else:
                    summary["linesUnmatched"].append((r["name"], ing["ingredientName"], "unit mismatch"))
            else:
                summary["linesUnmatched"].append((r["name"], ing["ingredientName"], match["status"]))

            conn.execute(
                "INSERT INTO RecipeLine (id, recipeId, itemId, subRecipeId, qty, rawIngredientName, "
                "rawQtyValue, rawQtyUnit, matchStatus, createdAt) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                (new_id(), recipe_id, item_id, converted_qty, ing["ingredientName"],
                 ing["qtyValue"], ing["qtyUnit"], match["status"] if not item_id else "AUTO", now_db()),
            )

    return summary
