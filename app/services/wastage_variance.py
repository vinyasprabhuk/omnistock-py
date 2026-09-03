"""
Produced vs Sold vs Wasted reconciliation, per recipe, in Litres (or
plates for a piece-counted recipe with no volume yield) -- confirmed in
chat as a quantity variance, not a percentage:

    variance = produced - sold - wasted

"Produced" and "Wasted" come from that date's Production/Wastage log
entries (via match_and_scale_entry, the same matcher used for the
ingredient breakdown). "Sold" comes from that date's REAL DishSale rows
(not Intent's predicted average) expanded through each dish's own recipe
and accompaniment rules -- same math as intent.py's generate_intent_day,
just driven by an actual day's sales instead of a 6-week average, so a
date with no sale report uploaded yet correctly shows "no sales data"
rather than a misleadingly large variance from a silent zero.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

import sqlite3

from app.services.intent_rules import accompaniments_for_dish
from app.services.wastage_ingredients import batch_ml_for_recipe, match_and_scale_entry


class SoldBreakdownEntry(TypedDict):
    dishName: str
    qty: float


class VarianceRow(TypedDict):
    recipeName: str
    produced: float
    sold: float
    wasted: float
    variance: float
    unit: str
    soldBreakdown: list[SoldBreakdownEntry]


def _recipe_litres_from_log(conn: sqlite3.Connection, table: str, date_db: str, branch_id: str) -> dict[str, float]:
    rows = conn.execute(
        f"SELECT description, weight, unit, pieces FROM {table} WHERE date = ? AND branchId = ?",
        (date_db, branch_id),
    ).fetchall()
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        result = match_and_scale_entry(conn, dict(row))
        recipe, multiplier = result["recipe"], result["multiplier"]
        if recipe is None or multiplier is None:
            continue
        batch_ml = batch_ml_for_recipe(recipe)
        totals[recipe["name"]] += (multiplier * batch_ml) / 1000.0
    return dict(totals)


def _recipe_litres_from_sales(
    conn: sqlite3.Connection, date_db: str,
) -> tuple[dict[str, float], dict[str, dict[str, float]], bool]:
    """Returns (recipe -> total litres sold, recipe -> {dishName: qtySold},
    salesAvailable). The per-dish breakdown lets the UI show exactly which
    sold dishes (own-recipe sales and/or accompaniment usage, e.g. every
    Idly sold carries a fixed serving of Sambar) were counted toward a
    recipe's Sold figure -- dish qtys are summed if a dish contributes to
    the same recipe more than once (own recipe + accompaniment)."""
    rows = conn.execute(
        "SELECT dishId, SUM(qty) AS qty FROM DishSale WHERE date = ? AND dishId IS NOT NULL GROUP BY dishId",
        (date_db,),
    ).fetchall()
    if not rows:
        return {}, {}, False

    totals: dict[str, float] = defaultdict(float)
    breakdown: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        dish = conn.execute("SELECT id, name, category FROM Dish WHERE id = ?", (row["dishId"],)).fetchone()
        if dish is None:
            continue
        qty = float(row["qty"])

        own_recipe = conn.execute("SELECT * FROM Recipe WHERE dishId = ?", (dish["id"],)).fetchone()
        if own_recipe and own_recipe["portionSizeMl"]:
            totals[own_recipe["name"]] += (qty * own_recipe["portionSizeMl"]) / 1000.0
            breakdown[own_recipe["name"]][dish["name"]] += qty

        for entry in accompaniments_for_dish(dish["category"], dish["name"]):
            if entry["refType"] != "RECIPE":
                continue
            recipe = conn.execute("SELECT * FROM Recipe WHERE name = ?", (entry["refName"],)).fetchone()
            if recipe is None:
                continue
            totals[recipe["name"]] += (qty * entry["qty"]) / 1000.0
            breakdown[recipe["name"]][dish["name"]] += qty

    return dict(totals), {k: dict(v) for k, v in breakdown.items()}, True


def compute_variance(conn: sqlite3.Connection, date_db: str, branch_id: str) -> dict:
    produced = _recipe_litres_from_log(conn, "ProductionLog", date_db, branch_id)
    wasted = _recipe_litres_from_log(conn, "Wastage", date_db, branch_id)
    sold, sold_breakdown, sales_available = _recipe_litres_from_sales(conn, date_db)

    recipe_names = set(produced) | set(wasted) | set(sold)
    rows: list[VarianceRow] = []
    for name in recipe_names:
        p, s, w = produced.get(name, 0.0), sold.get(name, 0.0), wasted.get(name, 0.0)
        breakdown = sorted(
            ({"dishName": d, "qty": round(q, 2)} for d, q in sold_breakdown.get(name, {}).items()),
            key=lambda b: -b["qty"],
        )
        rows.append({
            "recipeName": name, "produced": round(p, 2), "sold": round(s, 2),
            "wasted": round(w, 2), "variance": round(p - s - w, 2), "unit": "L",
            "soldBreakdown": breakdown,
        })
    rows.sort(key=lambda r: -abs(r["variance"]))

    return {"rows": rows, "salesAvailable": sales_available}
