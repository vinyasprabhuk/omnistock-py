"""
The accompaniment rules confirmed in chat for the Intent feature -- fixed
portions of a side recipe (or a plain item, for Curd/Appalam which need no
recipe expansion) added automatically whenever a dish in the matching
category is sold. Kept as plain Python data rather than a database table:
there are only a handful of these, they rarely change, and reviewing a diff
here is far easier than reviewing rows in an admin UI for something this
small (see the project's general "no premature abstraction" convention).

refType 'RECIPE' entries are looked up by Recipe.name; 'RECIPE_MISSING'
entries are the ones nobody has a real recipe for yet (chutneys, "coconut
stuff", "channa masala") -- Intent generation reports these as a gap for
that dish rather than silently omitting the accompaniment or guessing at
its ingredients.
"""
from __future__ import annotations

from typing import TypedDict


class AccompanimentEntry(TypedDict):
    refType: str  # 'RECIPE' | 'RECIPE_MISSING' | 'ITEM'
    refName: str
    qty: float
    unit: str  # 'ml' | 'piece'


# Categories covered by the Group A default (chutneys + sambar). Chaat is
# deliberately excluded, per "except chaat" in the confirmed rule.
GROUP_A_CATEGORIES = {"DOSA", "IDLY", "PONGAL_KARABATH", "VADA", "SNACKS", "POORI"}

GROUP_A_DEFAULT: list[AccompanimentEntry] = [
    {"refType": "RECIPE_MISSING", "refName": "Coconut Chutney", "qty": 50, "unit": "ml"},
    {"refType": "RECIPE_MISSING", "refName": "Tomato Chutney", "qty": 50, "unit": "ml"},
    {"refType": "RECIPE_MISSING", "refName": "Mint Chutney", "qty": 50, "unit": "ml"},
]

# The sambar variant is chosen per-dish (Bengaluru-style dosas get Bengaluru
# Sambar, everything else gets Tamilnadu Sambar) -- see intent.py.
SAMBAR_DEFAULT_RECIPE = "Tamilnadu Sambar"
SAMBAR_BENGALURU_RECIPE = "Bengaluru Sambar"
SAMBAR_PORTION_ML = 100

# Per-dish additions on top of the Group A default, matched by a case
# insensitive substring of the dish name.
GROUP_A_DISH_ADDITIONS: list[tuple[str, AccompanimentEntry]] = [
    ("poori", {"refType": "RECIPE", "refName": "Poori Masala", "qty": 100, "unit": "ml"}),
    ("neer dosa", {"refType": "RECIPE_MISSING", "refName": "Coconut Stuff", "qty": 100, "unit": "ml"}),
    ("channa batura", {"refType": "RECIPE_MISSING", "refName": "Channa Masala", "qty": 100, "unit": "ml"}),
    ("set dosa", {"refType": "RECIPE", "refName": "Vadakari", "qty": 100, "unit": "ml"}),
]

# Meals/thali: every side at 100ml, sambar alone at 200ml (confirmed).
GROUP_B_CATEGORY = "MEALS"
GROUP_B_SIDES: list[AccompanimentEntry] = [
    {"refType": "RECIPE", "refName": "Kootu", "qty": 100, "unit": "ml"},
    {"refType": "RECIPE", "refName": "Poriyal", "qty": 100, "unit": "ml"},
    {"refType": "ITEM", "refName": "Curd", "qty": 100, "unit": "ml"},
    {"refType": "RECIPE", "refName": "Kara Kuuzhambu", "qty": 100, "unit": "ml"},
    {"refType": "RECIPE", "refName": "Rasam", "qty": 100, "unit": "ml"},
    {"refType": "RECIPE", "refName": "Payasam", "qty": 100, "unit": "ml"},
    {"refType": "RECIPE", "refName": "Meals Sambar", "qty": 200, "unit": "ml"},
]

# Variety rice / bisibelebath / curd rice: poriyal + appalam.
GROUP_C_CATEGORY = "VARIETY_RICE"
GROUP_C_SIDES: list[AccompanimentEntry] = [
    {"refType": "RECIPE", "refName": "Poriyal", "qty": 100, "unit": "ml"},
    {"refType": "ITEM", "refName": "Appalam", "qty": 1, "unit": "piece"},
]


def accompaniments_for_dish(category: str, dish_name: str) -> list[AccompanimentEntry]:
    """Every accompaniment entry that applies to one dish, by its
    intent-rule category and its own name (for the per-dish additions and
    the Bengaluru-sambar override)."""
    name_lower = dish_name.lower()
    entries: list[AccompanimentEntry] = []

    if category in GROUP_A_CATEGORIES:
        entries.extend(GROUP_A_DEFAULT)
        sambar_recipe = SAMBAR_BENGALURU_RECIPE if "bengaluru" in name_lower else SAMBAR_DEFAULT_RECIPE
        entries.append({"refType": "RECIPE", "refName": sambar_recipe, "qty": SAMBAR_PORTION_ML, "unit": "ml"})
        for keyword, addition in GROUP_A_DISH_ADDITIONS:
            if keyword in name_lower:
                entries.append(addition)

    if category == GROUP_B_CATEGORY:
        entries.extend(GROUP_B_SIDES)

    if category == GROUP_C_CATEGORY:
        entries.extend(GROUP_C_SIDES)

    return entries
