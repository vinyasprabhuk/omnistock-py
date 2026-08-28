"""
Matches a Wastage/Production entry's free-text description (picked from
WastageMenuItem, e.g. "B. SAMBAR", "KARABATH") against the Recipe table, so
a logged waste/production entry can be translated into the ingredients it
represents. Same Sorensen-Dice approach as match_item.py/match_dish.py --
no alias table for recipes yet, matched directly against Recipe.name.
"""
from __future__ import annotations

import math
import sqlite3
from typing import TypedDict

from app.services.match_item import AUTO_THRESHOLD, REVIEW_THRESHOLD, compare_two_strings, normalize


class RecipeMatchResult(TypedDict):
    matchedRecipeId: str | None
    matchedRecipeName: str | None
    confidence: float
    status: str  # AUTO | REVIEW | MANUAL


def match_recipe(conn: sqlite3.Connection, extracted_text: str) -> RecipeMatchResult:
    recipes = conn.execute("SELECT id, name FROM Recipe ORDER BY rowid ASC").fetchall()

    target = normalize(extracted_text)
    best: dict | None = None
    for recipe in recipes:
        aliases = conn.execute(
            "SELECT alias FROM RecipeAlias WHERE recipeId = ? ORDER BY rowid ASC", (recipe["id"],)
        ).fetchall()
        candidates = [normalize(recipe["name"])] + [normalize(a["alias"]) for a in aliases]
        for candidate in candidates:
            score = compare_two_strings(target, candidate) * 100
            if best is None or score > best["score"]:
                best = {"recipeId": recipe["id"], "recipeName": recipe["name"], "score": score}

    if best is None:
        return {"matchedRecipeId": None, "matchedRecipeName": None, "confidence": 0, "status": "MANUAL"}

    confidence = math.floor(best["score"] * 100 + 0.5) / 100
    if confidence >= AUTO_THRESHOLD:
        status = "AUTO"
    elif confidence >= REVIEW_THRESHOLD:
        status = "REVIEW"
    else:
        status = "MANUAL"

    return {
        "matchedRecipeId": best["recipeId"], "matchedRecipeName": best["recipeName"],
        "confidence": confidence, "status": status,
    }


def save_recipe_alias(conn: sqlite3.Connection, recipe_id: str, alias: str) -> None:
    from app.dates import now_db
    from app.db import new_id

    normalized = normalize(alias)
    existing = conn.execute("SELECT id FROM RecipeAlias WHERE alias = ?", (normalized,)).fetchone()
    if existing:
        conn.execute("UPDATE RecipeAlias SET recipeId = ? WHERE alias = ?", (recipe_id, normalized))
    else:
        conn.execute(
            "INSERT INTO RecipeAlias (id, recipeId, alias, createdAt) VALUES (?, ?, ?, ?)",
            (new_id(), recipe_id, normalized, now_db()),
        )
