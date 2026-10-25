"""
Scales one recipe to a requested quantity (kg or pax) and costs each
ingredient -- the Recipe page's "how much do I need for 6 kg" calculator.

Scaling follows the same convention as Production/Wastage logging
(wastage_ingredients.match_and_scale_entry): kg is converted to ml at
1 kg = 1 litre and divided by the recipe's batch size
(batch_ml_for_recipe); pax divides by the recipe's servesQty. Using the
same math means this page never disagrees with what a logged Production
entry of the same size would consume.

Cost per ingredient is scaled qty x Item.purchasePrice (RecipeLine.qty is
already stored in the Item's own unit). A line with no Item match, or an
Item with no price set, can't be costed -- it is still listed at its
scaled raw quantity but left out of the total, and counted so the caller
can say the total is partial rather than silently understating it.
"""
from __future__ import annotations

import math
import sqlite3

from app.services.wastage_ingredients import _WEIGHT_TO_ML, batch_ml_for_recipe

MODES = ("kg", "pax")


def _batch_kg(recipe: sqlite3.Row) -> float | None:
    batch_ml = batch_ml_for_recipe(recipe)
    return batch_ml / _WEIGHT_TO_ML["KG"] if batch_ml else None


def recipe_yields(recipe: sqlite3.Row) -> dict:
    """What one full batch makes, for showing next to the input."""
    return {"kg": _batch_kg(recipe), "pax": recipe["servesQty"] or None}


def scale_recipe(conn: sqlite3.Connection, recipe_id: str, mode: str, value: str | float) -> dict:
    """Raises LookupError for an unknown recipe, ValueError (with a
    message fit to show the user) for bad input or a recipe that has no
    yield recorded for the requested mode."""
    recipe = conn.execute("SELECT * FROM Recipe WHERE id = ?", (recipe_id,)).fetchone()
    if recipe is None:
        raise LookupError(recipe_id)

    mode = (mode or "").lower()
    if mode not in MODES:
        raise ValueError("Choose kg or pax.")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError("Enter a number.") from None
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Enter a number greater than zero.")

    yields = recipe_yields(recipe)
    if yields[mode] is None:
        raise ValueError(f"{recipe['name']} has no {mode} yield recorded, so it can't be scaled by {mode}.")
    multiplier = amount / yields[mode]

    rows = conn.execute(
        "SELECT rl.qty, rl.rawIngredientName, rl.rawQtyValue, rl.rawQtyUnit, rl.itemId, "
        "i.name AS itemName, i.unit AS itemUnit, i.purchasePrice AS price "
        "FROM RecipeLine rl LEFT JOIN Item i ON i.id = rl.itemId "
        "WHERE rl.recipeId = ? ORDER BY rl.rowid",
        (recipe_id,),
    ).fetchall()

    lines, total_cost, uncosted = [], 0.0, 0
    for r in rows:
        if r["itemId"] and r["itemName"]:
            qty = float(r["qty"]) * multiplier
            price = float(r["price"] or 0)
            cost = qty * price if price > 0 else None
            line = {"name": r["itemName"], "qty": qty, "unit": r["itemUnit"], "price": price or None,
                    "cost": cost, "matched": True}
        else:
            line = {"name": r["rawIngredientName"], "qty": float(r["rawQtyValue"]) * multiplier,
                    "unit": r["rawQtyUnit"], "price": None, "cost": None, "matched": False}
        if line["cost"] is None:
            uncosted += 1
        else:
            total_cost += line["cost"]
        lines.append(line)

    return {
        "recipeName": recipe["name"], "mode": mode, "amount": amount, "multiplier": multiplier,
        "yieldKg": yields["kg"], "yieldPax": yields["pax"],
        "lines": lines, "totalCost": total_cost, "uncostedCount": uncosted,
    }
