"""
Loads parsed recipe.docx recipes into Dish/Recipe/RecipeLine, matching each
ingredient line against Item Master via the existing item matcher and
converting the recipe doc's raw unit (grams/ml/kg/pieces) into whatever unit
the matched Item actually uses. A line whose ingredient has no confident
Item Master match keeps itemId NULL and its raw name/qty/unit intact, so it
can be resolved later (see matchStatus) once the missing item is added --
nothing about it is guessed at import time.

Add-only: a recipe whose name is already in the app -- the same name, or a
close automatic match to one (e.g. "Tamil Nadu Sambar" vs "Tamilnadu
Sambar") -- is skipped and reported, never overwritten, so re-uploading a
doc is safe and only brings in recipes that are genuinely new. The check
runs against what existed before the upload, so two new recipes in one doc
never skip each other. A recipe is linked to a Dish only when a Dish with that exact name
already exists (created from real POS sales) -- never fabricated here, so
an accompaniment-only recipe (Sambar, Kootu, ...) stays unlinked until the
matching dish genuinely shows up in sales.
"""
from __future__ import annotations

import sqlite3

from app.db import new_id
from app.dates import now_db
from app.parsing.recipe_docx import ParsedRecipe, parse_recipe_docx
from app.services.match_item import match_item
from app.services.match_recipe import match_recipe

_WEIGHT = {"g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0}
_VOLUME = {"ml": 1.0, "l": 1000.0, "litre": 1000.0, "liter": 1000.0, "ltr": 1000.0}
_COUNT = {"piece": 1.0, "pieces": 1.0, "pcs": 1.0, "pc": 1.0, "nos": 1.0, "no": 1.0, "": 1.0}

# What a recipe's counted or spooned unit weighs, per Item (lower-case name),
# in grams -- so "6 pieces" of Green chilly or "3 spoons" of Chilly Powder can
# be costed against an item that is priced per Kg. Supplied by the kitchen;
# an item/unit pair not listed here stays unmatched rather than guessed at.
_UNIT_KIND = {**{u: "count" for u in _COUNT}, "clove": "clove", "cloves": "clove",
              "coconut": "coconut", "coconuts": "coconut", "spoon": "spoon", "spoons": "spoon",
              "bunch": "bunch", "bunches": "bunch"}
UNIT_GRAMS = {
    "green chilly": {"count": 5},
    "red chilli": {"count": 5},
    "garlic": {"clove": 5},
    "coconut": {"coconut": 850 / 3, "count": 850 / 3},
    "drumsticks": {"count": 120},
    "capsicum": {"count": 200},
    "raw banana": {"count": 120},
    "banana": {"count": 118},
    "cashew": {"count": 4},
    "cauliflower": {"count": 300},
    "coriander leaves": {"bunch": 80},
    "chilly powder": {"spoon": 30},
    "turmeric powder": {"spoon": 30},
    "pepper": {"spoon": 20},
}

# Grams of the item behind one ml of what the recipe lists: 250 ml of tamarind
# extract is made from 50 g of tamarind.
ML_TO_GRAMS = {"tamarind": 50 / 250}

# A recipe line that names another recipe, under a different spelling.
SUB_RECIPE_ALIASES = {"mini idli batter": "idli batter"}


def _convert_qty(value: float, raw_unit: str, target_unit: str, item_name: str | None = None) -> float | None:
    """Converts a recipe-doc quantity (in raw_unit) into target_unit's scale.
    Returns None if the two units aren't in the same family (weight/volume/count).

    The recipe doc measures liquids like oil, milk and curd in grams even
    though Item Master tracks them in Litres -- a weight/volume mismatch, not
    a bad match. Falls back to a 1 gram = 1 ml density assumption in that
    case (accurate for milk/curd, a reasonable approximation for oil) rather
    than leaving those lines unmatched."""
    raw_unit = raw_unit.lower()
    target = target_unit.lower()
    extract = ML_TO_GRAMS.get((item_name or "").strip().lower())
    if extract is not None and raw_unit in _VOLUME and target in ("kg", "litre"):
        return value * _VOLUME[raw_unit] * extract / 1000.0
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
    grams = UNIT_GRAMS.get((item_name or "").strip().lower(), {}).get(_UNIT_KIND.get(raw_unit))
    if grams is not None and target in ("kg", "litre"):
        return value * grams / 1000.0
    return None


def load_recipes_from_docx(conn: sqlite3.Connection, docx_path: str) -> dict:
    recipes = parse_recipe_docx(docx_path)
    summary = {"recipesLoaded": 0, "recipesSkipped": [], "dishesLinked": 0,
               "linesMatched": 0, "linesUnmatched": []}

    # Decide every skip before writing anything, so the matcher only ever
    # compares against recipes that existed before this upload.
    to_load: list[ParsedRecipe] = []
    seen: set[str] = set()
    for r in recipes:
        key = r["name"].strip().lower()
        if key in seen:
            summary["recipesSkipped"].append((r["name"], "repeated in this file"))
            continue
        seen.add(key)
        exact = conn.execute("SELECT name FROM Recipe WHERE lower(name) = ?", (key,)).fetchone()
        if exact:
            summary["recipesSkipped"].append((r["name"], exact["name"]))
            continue
        near = match_recipe(conn, r["name"])
        if near["status"] == "AUTO":
            summary["recipesSkipped"].append((r["name"], near["matchedRecipeName"]))
            continue
        to_load.append(r)

    for r in to_load:
        r: ParsedRecipe
        # Exact (case-insensitive) name match only -- fuzzy matching here
        # risks linking an accompaniment-only recipe (e.g. "Tamilnadu
        # Sambar") to an unrelated real dish that merely sounds similar
        # (e.g. a standalone "Sambar" item).
        dish_row = conn.execute(
            "SELECT id FROM Dish WHERE lower(name) = lower(?) AND active = 1", (r["name"],)
        ).fetchone()
        dish_id = dish_row["id"] if dish_row else None
        if dish_id:
            summary["dishesLinked"] += 1

        ts = now_db()
        recipe_id = new_id()
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
                    "SELECT name, unit FROM Item WHERE id = ?", (match["matchedItemId"],)
                ).fetchone()
                converted = _convert_qty(ing["qtyValue"], ing["qtyUnit"], item_row["unit"], item_row["name"])
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


def expand_subrecipe_lines(conn: sqlite3.Connection) -> int:
    """A line with no Item whose name is another recipe ("Idli batter 110 g",
    "Potato masala 40 g") is replaced by that recipe's own ingredients,
    scaled to the quantity used -- so the batter's rice, dal and so on are
    costed instead of one unpriceable text line. Uses the same 1 g = 1 ml
    scale as the rest of the app, and skips a recipe with no batch size."""
    from app.services.wastage_ingredients import batch_ml_for_recipe

    lines = conn.execute(
        "SELECT id, recipeId, rawIngredientName, rawQtyValue, rawQtyUnit FROM RecipeLine "
        "WHERE itemId IS NULL AND subRecipeId IS NULL ORDER BY rowid"
    ).fetchall()
    expanded = 0
    for line in lines:
        key = line["rawIngredientName"].strip().lower()
        sub = conn.execute(
            "SELECT * FROM Recipe WHERE lower(name) = ? AND id != ?",
            (SUB_RECIPE_ALIASES.get(key, key), line["recipeId"]),
        ).fetchone()
        unit = line["rawQtyUnit"].lower()
        if sub is None or (unit not in _WEIGHT and unit not in _VOLUME):
            continue
        batch_ml = batch_ml_for_recipe(sub)
        sub_lines = conn.execute(
            "SELECT itemId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, matchStatus FROM RecipeLine "
            "WHERE recipeId = ? AND subRecipeId IS NULL ORDER BY rowid", (sub["id"],)
        ).fetchall()
        if not batch_ml or not sub_lines:
            continue
        used_ml = line["rawQtyValue"] * (_WEIGHT.get(unit) or _VOLUME[unit])
        scale = used_ml / batch_ml
        for sl in sub_lines:
            conn.execute(
                "INSERT INTO RecipeLine (id, recipeId, itemId, subRecipeId, qty, rawIngredientName, "
                "rawQtyValue, rawQtyUnit, matchStatus, createdAt) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                (new_id(), line["recipeId"], sl["itemId"], sl["qty"] * scale, sl["rawIngredientName"],
                 sl["rawQtyValue"] * scale, sl["rawQtyUnit"], sl["matchStatus"], now_db()),
            )
        conn.execute("DELETE FROM RecipeLine WHERE id = ?", (line["id"],))
        expanded += 1
    return expanded


def rematch_unmatched_lines(conn: sqlite3.Connection) -> dict:
    """Retries every recipe line that has no Item yet -- for after items or
    aliases were added to Item Master. First swaps any line that is really
    another recipe for that recipe's ingredients, then links only a
    confident (AUTO) match whose unit converts, exactly like at upload time;
    anything else is left as it was.

    A line that already has an Item is left alone, with one exception: a line
    sitting on an item with no price is re-checked, and moves to a priced item
    the name now matches confidently (a wrong alias that pointed at a free
    item, once corrected, would otherwise leave its lines costing nothing)."""
    expanded = expand_subrecipe_lines(conn)
    lines = conn.execute(
        "SELECT id, rawIngredientName, rawQtyValue, rawQtyUnit FROM RecipeLine "
        "WHERE itemId IS NULL AND subRecipeId IS NULL ORDER BY rowid"
    ).fetchall()
    linked = 0
    for line in lines:
        match = match_item(conn, line["rawIngredientName"])
        if match["status"] != "AUTO" or not match["matchedItemId"]:
            continue
        item = conn.execute("SELECT name, unit FROM Item WHERE id = ?", (match["matchedItemId"],)).fetchone()
        qty = _convert_qty(line["rawQtyValue"], line["rawQtyUnit"], item["unit"], item["name"])
        if qty is None:
            continue
        conn.execute(
            "UPDATE RecipeLine SET itemId = ?, qty = ?, matchStatus = 'AUTO' WHERE id = ?",
            (match["matchedItemId"], qty, line["id"]),
        )
        linked += 1

    moved = 0
    unpriced = conn.execute(
        "SELECT rl.id, rl.itemId, rl.rawIngredientName, rl.rawQtyValue, rl.rawQtyUnit FROM RecipeLine rl "
        "JOIN Item i ON i.id = rl.itemId WHERE COALESCE(i.purchasePrice, 0) <= 0 AND rl.subRecipeId IS NULL "
        "ORDER BY rl.rowid"
    ).fetchall()
    for line in unpriced:
        match = match_item(conn, line["rawIngredientName"])
        if match["status"] != "AUTO" or not match["matchedItemId"] or match["matchedItemId"] == line["itemId"]:
            continue
        item = conn.execute(
            "SELECT name, unit, purchasePrice FROM Item WHERE id = ?", (match["matchedItemId"],)
        ).fetchone()
        if not (item["purchasePrice"] or 0) > 0:
            continue
        qty = _convert_qty(line["rawQtyValue"], line["rawQtyUnit"], item["unit"], item["name"])
        if qty is None:
            continue
        conn.execute("UPDATE RecipeLine SET itemId = ?, qty = ?, matchStatus = 'AUTO' WHERE id = ?",
                     (match["matchedItemId"], qty, line["id"]))
        moved += 1
    return {"checked": len(lines), "linked": linked, "stillUnmatched": len(lines) - linked,
            "expanded": expanded, "moved": moved}
