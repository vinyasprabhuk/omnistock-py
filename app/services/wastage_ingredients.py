"""
Translates logged Wastage/Production entries into the raw ingredients they
represent, via the same recipe-batch scaling used by Intent
(app/services/intent.py) -- just driven by an actually-logged qty instead
of a predicted one. Reuses expand_recipe_items so a recipe's ingredients
scale identically everywhere they're used.

Only an AUTO-confidence match to a real Recipe is used to compute
ingredients; a REVIEW/MANUAL match or an entry with no recipe at all is
still shown against the entry (so the logged item is never displayed
un-associated), but contributes to `gaps` instead of guessed ingredient
numbers.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

import sqlite3

from app.services.intent import expand_recipe_items
from app.services.match_recipe import match_recipe

_WEIGHT_TO_ML = {"KG": 1000.0, "GM": 1.0}


class IngredientLine(TypedDict):
    itemName: str
    unit: str
    qty: float
    groupLabel: str
    spend: float


def compute_wasted_ingredients(conn: sqlite3.Connection, entries: list[dict]) -> dict:
    matched_entries: list[dict] = []
    item_totals: dict[tuple[str, str], float] = defaultdict(float)
    gaps: list[dict] = []

    for entry in entries:
        match = match_recipe(conn, entry["description"])
        entry_with_match = {
            **entry, "matchedRecipeName": match["matchedRecipeName"],
            "matchStatus": match["status"], "matchConfidence": match["confidence"],
        }
        matched_entries.append(entry_with_match)

        if match["status"] != "AUTO":
            gaps.append({
                "description": entry["description"],
                "reason": f"no confident recipe match (best guess: {match['matchedRecipeName'] or 'none'})",
            })
            continue

        recipe = conn.execute("SELECT * FROM Recipe WHERE id = ?", (match["matchedRecipeId"],)).fetchone()

        multiplier = None
        if entry["pieces"]:
            if recipe["servesQty"]:
                multiplier = float(entry["pieces"]) / recipe["servesQty"]
            else:
                gaps.append({"description": entry["description"], "reason": f"{recipe['name']} recipe has no pax yield to scale pieces against"})
        elif entry["weight"] is not None:
            weight_ml = float(entry["weight"]) * _WEIGHT_TO_ML.get(entry["unit"], 1.0)
            batch_ml = (recipe["servesVolumeLitre"] * 1000.0 if recipe["servesVolumeLitre"]
                        else (recipe["servesQty"] or 0) * (recipe["portionSizeMl"] or 0))
            if batch_ml:
                multiplier = weight_ml / batch_ml
            else:
                gaps.append({"description": entry["description"], "reason": f"{recipe['name']} recipe has no batch yield to scale from"})
        else:
            gaps.append({"description": entry["description"], "reason": "no weight or piece count logged"})

        if multiplier is None:
            continue

        for item_id, qty in expand_recipe_items(conn, recipe["id"], multiplier).items():
            item_totals[(item_id, recipe["name"])] += qty

    lines: list[IngredientLine] = []
    total_spend = 0.0
    for (item_id, group_label), qty in item_totals.items():
        item = conn.execute("SELECT name, unit, purchasePrice FROM Item WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            continue
        spend = round(qty * float(item["purchasePrice"]), 2)
        total_spend += spend
        lines.append({"itemName": item["name"], "unit": item["unit"], "qty": round(qty, 3),
                      "groupLabel": group_label, "spend": spend})
    lines.sort(key=lambda l: (l["groupLabel"], -l["qty"]))

    return {"entries": matched_entries, "lines": lines, "gaps": gaps, "totalSpend": round(total_spend, 2)}
