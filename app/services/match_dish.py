"""
Dish-name matching for the Intent feature -- same Sorensen-Dice approach as
match_item.py (see that module for the algorithm notes), applied to the
Dish/DishAlias tables instead of Item/ItemAlias so POS sale-report item text
("Sambar Vada(1pc)", "Sambar Vada (1 Pcs) [qsr]") resolves to one canonical
Dish even when the wording varies across export channels.
"""
from __future__ import annotations

import math
import sqlite3
from typing import TypedDict

from app.services.match_item import AUTO_THRESHOLD, REVIEW_THRESHOLD, compare_two_strings, normalize


class DishMatchResult(TypedDict):
    matchedDishId: str | None
    matchedDishName: str | None
    confidence: float
    status: str  # AUTO | REVIEW | MANUAL


def match_dish(conn: sqlite3.Connection, extracted_text: str) -> DishMatchResult:
    dishes = conn.execute(
        "SELECT id, name FROM Dish WHERE active = 1 ORDER BY rowid ASC"
    ).fetchall()

    target = normalize(extracted_text)
    best: dict | None = None

    for dish in dishes:
        aliases = conn.execute(
            "SELECT alias FROM DishAlias WHERE dishId = ? ORDER BY rowid ASC", (dish["id"],)
        ).fetchall()
        candidates = [normalize(dish["name"])] + [normalize(a["alias"]) for a in aliases]
        for candidate in candidates:
            score = compare_two_strings(target, candidate) * 100
            if best is None or score > best["score"]:
                best = {"dishId": dish["id"], "dishName": dish["name"], "score": score}

    if best is None:
        return {"matchedDishId": None, "matchedDishName": None, "confidence": 0, "status": "MANUAL"}

    confidence = math.floor(best["score"] * 100 + 0.5) / 100
    if confidence >= AUTO_THRESHOLD:
        status = "AUTO"
    elif confidence >= REVIEW_THRESHOLD:
        status = "REVIEW"
    else:
        status = "MANUAL"

    return {
        "matchedDishId": best["dishId"], "matchedDishName": best["dishName"],
        "confidence": confidence, "status": status,
    }


def save_dish_alias(conn: sqlite3.Connection, dish_id: str, alias: str) -> None:
    from app.dates import now_db
    from app.db import new_id

    normalized = normalize(alias)
    existing = conn.execute("SELECT id FROM DishAlias WHERE alias = ?", (normalized,)).fetchone()
    if existing:
        conn.execute("UPDATE DishAlias SET dishId = ? WHERE alias = ?", (dish_id, normalized))
    else:
        conn.execute(
            "INSERT INTO DishAlias (id, dishId, alias, createdAt) VALUES (?, ?, ?, ?)",
            (new_id(), dish_id, normalized, now_db()),
        )
