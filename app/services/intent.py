"""
Generates a weekly Intent day: predicted dish counts from the last N
same-weekday sales (default 6, per the confirmed "average of last 6
Mondays" rule), then expands each dish's own recipe plus its accompaniment
rules (intent_rules.py) into a per-item, per-department ingredient total.

Two different scaling bases, both anchored to a recipe's batch yield:
  - a dish's OWN recipe scales by predicted_qty / recipe.servesQty (plates
    sold vs. plates the batch yields)
  - an accompaniment RECIPE entry scales by the ml actually needed
    (predicted_qty * portion_ml) against the batch's total ml yield
    (servesQty * portionSizeMl, cross-checked against servesVolumeLitre)
A dish or accompaniment recipe that doesn't exist yet is reported as a gap,
never silently skipped or guessed at.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import TypedDict

from app.db import new_id
from app.dates import date_key_to_db, from_db, now_db, to_db
from app.services.intent_rules import accompaniments_for_dish

_UNIT_TO_ML_OR_G = {"ml": 1.0, "piece": 1.0}


def _weekday_history_dates(conn: sqlite3.Connection, target_date_db: str, weeks_back: int) -> list[str]:
    target_weekday = from_db(target_date_db).weekday()
    all_dates = [r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM DishSale WHERE date < ? ORDER BY date DESC", (target_date_db,)
    )]
    same_weekday = [d for d in all_dates if from_db(d).weekday() == target_weekday]
    return same_weekday[:weeks_back]


class PredictedDish(TypedDict):
    dishId: str
    dishName: str
    category: str
    departmentId: str
    predictedQty: float  # raw 6-week average, for display/audit
    finalQty: float  # what actually drives ingredient scaling (predictedQty, or an admin override)
    source: str  # 'AVG' | 'MANUAL'
    historyDates: list[str]
    historyQtys: list[float]


def predict_dish_counts(
    conn: sqlite3.Connection, date_key: str, weeks_back: int = 6,
    dish_overrides: dict[str, float] | None = None,
) -> list[PredictedDish]:
    """dish_overrides replaces the computed average for specific dishes with
    an admin-entered value (see intent.py's update_dish_count route) --
    those dishes still get the same recipe/accompaniment expansion, just
    from the overridden count instead of the 6-week average."""
    dish_overrides = dish_overrides or {}
    target_date_db = date_key_to_db(date_key)
    history_dates = _weekday_history_dates(conn, target_date_db, weeks_back)

    per_dish: dict[str, dict[str, float]] = defaultdict(dict)
    if history_dates:
        placeholders = ",".join("?" for _ in history_dates)
        rows = conn.execute(
            f"SELECT date, dishId, SUM(qty) qty FROM DishSale WHERE date IN ({placeholders}) AND dishId IS NOT NULL "
            "GROUP BY date, dishId", history_dates,
        ).fetchall()
        for r in rows:
            per_dish[r["dishId"]][r["date"]] = float(r["qty"])

    dish_ids = set(per_dish.keys()) | set(dish_overrides.keys())
    results: list[PredictedDish] = []
    for dish_id in dish_ids:
        dish = conn.execute(
            "SELECT id, name, category, departmentId FROM Dish WHERE id = ? AND active = 1", (dish_id,)
        ).fetchone()
        if dish is None:
            continue
        by_date = per_dish.get(dish_id, {})
        qtys = [by_date.get(d, 0.0) for d in history_dates]
        predicted = round(sum(qtys) / len(qtys), 1) if qtys else 0.0
        has_override = dish_id in dish_overrides
        final = dish_overrides[dish_id] if has_override else predicted
        if final <= 0:
            continue
        results.append({
            "dishId": dish["id"], "dishName": dish["name"], "category": dish["category"],
            "departmentId": dish["departmentId"], "predictedQty": predicted, "finalQty": final,
            "source": "MANUAL" if has_override else "AVG",
            "historyDates": history_dates, "historyQtys": qtys,
        })
    results.sort(key=lambda d: d["finalQty"], reverse=True)
    return results


def _recipe_by_name(conn: sqlite3.Connection, name: str):
    return conn.execute("SELECT * FROM Recipe WHERE name = ?", (name,)).fetchone()


def _expand_recipe_items(conn: sqlite3.Connection, recipe_id: str, multiplier: float) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for line in conn.execute(
        "SELECT itemId, qty FROM RecipeLine WHERE recipeId = ? AND itemId IS NOT NULL", (recipe_id,)
    ):
        totals[line["itemId"]] += float(line["qty"]) * multiplier
    return totals


class IntentGap(TypedDict):
    dishName: str
    reason: str


def generate_intent_day(
    conn: sqlite3.Connection, date_key: str, branch_id: str, weeks_back: int = 6,
    dish_overrides: dict[str, float] | None = None,
) -> dict:
    predicted = predict_dish_counts(conn, date_key, weeks_back, dish_overrides)
    date_db = date_key_to_db(date_key)

    # Keyed by (itemId, groupLabel) where groupLabel is the RECIPE that
    # actually needs the ingredient (e.g. "Tamilnadu Sambar"), not the dish
    # that triggered it (e.g. "Plain Dosa") -- so Toor Dhal shows up under
    # "Tamilnadu Sambar", never misleadingly attributed to "Dosa" just
    # because a dosa sale is what happened to need more sambar made.
    item_totals: dict[tuple[str, str], float] = defaultdict(float)
    gaps: list[IntentGap] = []
    dish_counts: list[PredictedDish] = []

    for d in predicted:
        own_recipe = conn.execute(
            "SELECT * FROM Recipe WHERE dishId = ?", (d["dishId"],)
        ).fetchone()
        if own_recipe and own_recipe["servesQty"]:
            multiplier = d["finalQty"] / own_recipe["servesQty"]
            for item_id, qty in _expand_recipe_items(conn, own_recipe["id"], multiplier).items():
                item_totals[(item_id, own_recipe["name"])] += qty
            dish_counts.append(d)
        elif d["category"] not in ("OTHER",):
            gaps.append({"dishName": d["dishName"], "reason": "no base recipe yet"})
            dish_counts.append(d)

        for entry in accompaniments_for_dish(d["category"], d["dishName"]):
            if entry["refType"] == "RECIPE_MISSING":
                gaps.append({"dishName": f"{d['dishName']} -> {entry['refName']}", "reason": "accompaniment recipe not provided yet"})
                continue
            if entry["refType"] == "ITEM":
                item = conn.execute("SELECT id, unit FROM Item WHERE name = ?", (entry["refName"],)).fetchone()
                if item is None:
                    gaps.append({"dishName": f"{d['dishName']} -> {entry['refName']}", "reason": "item not found in Item Master"})
                    continue
                total_needed = d["finalQty"] * entry["qty"]
                qty_in_item_unit = total_needed / 1000.0 if entry["unit"] == "ml" and item["unit"].lower() == "litre" else total_needed
                item_totals[(item["id"], entry["refName"])] += qty_in_item_unit
                continue
            recipe = _recipe_by_name(conn, entry["refName"])
            if recipe is None:
                gaps.append({"dishName": f"{d['dishName']} -> {entry['refName']}", "reason": "accompaniment recipe not found"})
                continue
            batch_ml = (recipe["servesVolumeLitre"] * 1000.0 if recipe["servesVolumeLitre"]
                        else (recipe["servesQty"] or 0) * (recipe["portionSizeMl"] or 0))
            if not batch_ml:
                gaps.append({"dishName": f"{d['dishName']} -> {entry['refName']}", "reason": "recipe has no batch yield to scale from"})
                continue
            ml_needed = d["finalQty"] * entry["qty"]
            multiplier = ml_needed / batch_ml
            for item_id, qty in _expand_recipe_items(conn, recipe["id"], multiplier).items():
                item_totals[(item_id, recipe["name"])] += qty

    existing = conn.execute(
        "SELECT id FROM IntentDay WHERE date = ? AND branchId = ?", (date_db, branch_id)
    ).fetchone()
    if existing:
        intent_day_id = existing["id"]
        conn.execute("DELETE FROM IntentDishCount WHERE intentDayId = ?", (intent_day_id,))
        conn.execute("DELETE FROM IntentIngredient WHERE intentDayId = ?", (intent_day_id,))
        conn.execute("UPDATE IntentDay SET updatedAt = ? WHERE id = ?", (now_db(), intent_day_id))
    else:
        intent_day_id = new_id()
        ts = now_db()
        conn.execute(
            "INSERT INTO IntentDay (id, date, branchId, status, createdAt, updatedAt) VALUES (?, ?, ?, 'DRAFT', ?, ?)",
            (intent_day_id, date_db, branch_id, ts, ts),
        )

    for d in dish_counts:
        ts = now_db()
        conn.execute(
            "INSERT INTO IntentDishCount (id, intentDayId, dishId, predictedQty, finalQty, source, createdAt, updatedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), intent_day_id, d["dishId"], d["predictedQty"], d["finalQty"], d["source"], ts, ts),
        )

    for (item_id, group_label), qty in item_totals.items():
        ts = now_db()
        conn.execute(
            "INSERT INTO IntentIngredient (id, intentDayId, itemId, groupLabel, qty, source, createdAt, updatedAt) "
            "VALUES (?, ?, ?, ?, ?, 'AUTO', ?, ?)",
            (new_id(), intent_day_id, item_id, group_label, round(qty, 3), ts, ts),
        )

    return {
        "intentDayId": intent_day_id,
        "dishesPredicted": len(dish_counts),
        "ingredientLines": len(item_totals),
        "gaps": gaps,
    }


def set_dish_override(conn: sqlite3.Connection, intent_day_id: str, dish_id: str, final_qty: float) -> dict:
    """Overrides one dish's predicted count and regenerates the whole day
    from it, so the ingredient table stays consistent with every dish count
    shown (including any earlier overrides on other dishes that day)."""
    day = conn.execute("SELECT date, branchId FROM IntentDay WHERE id = ?", (intent_day_id,)).fetchone()
    if day is None:
        raise ValueError("Intent day not found")

    overrides = {
        r["dishId"]: r["finalQty"] for r in conn.execute(
            "SELECT dishId, finalQty FROM IntentDishCount WHERE intentDayId = ? AND source = 'MANUAL'",
            (intent_day_id,),
        )
    }
    overrides[dish_id] = final_qty

    date_key = from_db(day["date"]).strftime("%Y-%m-%d")
    return generate_intent_day(conn, date_key, day["branchId"], dish_overrides=overrides)


class RecipePrep(TypedDict):
    recipeName: str
    totalLitres: float | None
    totalUnits: float | None
    unitLabel: str
    batchesNeeded: float | None
    batchSizeLabel: str
    contributors: list[str]


def compute_recipe_prep(conn: sqlite3.Connection, intent_day_id: str) -> list[RecipePrep]:
    """How much of each recipe (Sambar, Rasam, Kootu, ... and any dish's own
    recipe like Ghee Pongal) needs to be made that day -- read off the
    day's current dish counts (so it stays in sync with any dish-count
    overrides), not persisted separately."""
    dish_counts = conn.execute(
        "SELECT idc.dishId, idc.finalQty, dish.name AS dishName, dish.category AS category "
        "FROM IntentDishCount idc JOIN Dish dish ON dish.id = idc.dishId "
        "WHERE idc.intentDayId = ? ORDER BY idc.finalQty DESC",
        (intent_day_id,),
    ).fetchall()

    # Everything a recipe is used for -- as someone's own dish AND as an
    # accompaniment on other dishes -- draws from the same pot, so it's
    # tracked as one combined ml total per recipe rather than two separate
    # numbers that would otherwise show the same recipe name twice.
    ml_needed: dict[str, float] = defaultdict(float)
    contributor_qty: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for d in dish_counts:
        own_recipe = conn.execute(
            "SELECT name, portionSizeMl FROM Recipe WHERE dishId = ?", (d["dishId"],)
        ).fetchone()
        if own_recipe and own_recipe["portionSizeMl"]:
            ml_needed[own_recipe["name"]] += d["finalQty"] * own_recipe["portionSizeMl"]
            contributor_qty[own_recipe["name"]][d["dishName"]] += d["finalQty"]

        for entry in accompaniments_for_dish(d["category"], d["dishName"]):
            if entry["refType"] != "RECIPE":
                continue
            ml_needed[entry["refName"]] += d["finalQty"] * entry["qty"]
            contributor_qty[entry["refName"]][d["dishName"]] += d["finalQty"]

    results: list[RecipePrep] = []
    for name, ml in ml_needed.items():
        recipe = conn.execute("SELECT * FROM Recipe WHERE name = ?", (name,)).fetchone()
        if recipe is None:
            continue
        batch_ml = (recipe["servesVolumeLitre"] * 1000.0 if recipe["servesVolumeLitre"]
                    else (recipe["servesQty"] or 0) * (recipe["portionSizeMl"] or 0))
        batches = round(ml / batch_ml, 2) if batch_ml else None
        batch_label = (f"{recipe['servesQty']:g} pax" if recipe["servesQty"] else "") + (
            f" / {recipe['servesVolumeLitre']:g}L batch" if recipe["servesVolumeLitre"] else " batch")
        top_contributors = sorted(contributor_qty[name].items(), key=lambda kv: -kv[1])
        labels = [f"{dish_name} ×{qty:g}" for dish_name, qty in top_contributors[:5]]
        if len(top_contributors) > 5:
            labels.append(f"+{len(top_contributors) - 5} more")
        results.append({
            "recipeName": name, "totalLitres": round(ml / 1000.0, 2), "totalUnits": None,
            "unitLabel": "Litres", "batchesNeeded": batches, "batchSizeLabel": batch_label,
            "contributors": labels,
        })

    results.sort(key=lambda r: -(r["totalLitres"] or 0))
    return results
