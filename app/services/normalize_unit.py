"""Port of src/lib/inventory/normalizeUnit.ts. Unit FAMILIES are never
cross-converted (LITRE never becomes KG, etc); only weight-unit spellings
collapse into KG. Unrecognized units are flagged for review, never guessed."""
from __future__ import annotations

from typing import TypedDict

WEIGHT_TO_KG = {"KG": 1, "KGS": 1, "GM": 0.001, "GRAM": 0.001, "GRAMS": 0.001, "G": 0.001}

CANONICAL_UNITS = {
    "KG": "KG", "KGS": "KG", "GM": "KG", "GRAM": "KG", "GRAMS": "KG", "G": "KG",
    "LIT": "LITRE", "LITRE": "LITRE", "LITRES": "LITRE", "L": "LITRE",
    "PACK": "PACK", "PACKS": "PACK",
    "PCS": "PCS", "PC": "PCS", "PIECE": "PCS", "PIECES": "PCS",
    "BOX": "BOX", "BOXES": "BOX",
    "BOTTLE": "BOTTLES", "BOTTLES": "BOTTLES",
}


class NormalizedQuantity(TypedDict):
    qty: float
    unit: str
    ambiguous: bool


def normalize_unit(raw_qty: float, raw_unit: str | None) -> NormalizedQuantity:
    if not raw_unit or not raw_unit.strip():
        return {"qty": raw_qty, "unit": "", "ambiguous": True}

    key = raw_unit.strip().upper()
    canonical = CANONICAL_UNITS.get(key)

    if not canonical:
        return {"qty": raw_qty, "unit": raw_unit.strip(), "ambiguous": True}

    if canonical == "KG" and key in WEIGHT_TO_KG:
        return {"qty": raw_qty * WEIGHT_TO_KG[key], "unit": "KG", "ambiguous": False}

    return {"qty": raw_qty, "unit": canonical, "ambiguous": False}
