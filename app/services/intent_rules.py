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

# Combo/tiffin platters -- keyed by exact dish name rather than category,
# confirmed in chat. Components with no recipe of their own yet (Idly,
# Vada, Masala Dosa batters, chutneys, Filter Coffee) are RECIPE_MISSING so
# they show as a real gap instead of silently vanishing, same as every
# other unresolved accompaniment.
COMBO_COMPOSITIONS: dict[str, list[AccompanimentEntry]] = {
    "Mini Tiffin": [
        {"refType": "RECIPE", "refName": "Kesari", "qty": 70, "unit": "ml"},
        {"refType": "RECIPE", "refName": "Ghee Pongal", "qty": 200, "unit": "ml"},
        {"refType": "RECIPE", "refName": "Tamilnadu Sambar", "qty": 100, "unit": "ml"},
        {"refType": "RECIPE_MISSING", "refName": "Idly (1 pc, in Mini Tiffin)", "qty": 1, "unit": "piece"},
        {"refType": "RECIPE_MISSING", "refName": "Vada (half, in Mini Tiffin)", "qty": 0.5, "unit": "piece"},
        {"refType": "RECIPE_MISSING", "refName": "Masala Dosa (half, in Mini Tiffin)", "qty": 0.5, "unit": "piece"},
        {"refType": "RECIPE_MISSING", "refName": "Coconut Chutney", "qty": 50, "unit": "ml"},
        {"refType": "RECIPE_MISSING", "refName": "Tomato Chutney", "qty": 50, "unit": "ml"},
        {"refType": "RECIPE_MISSING", "refName": "Mint Chutney", "qty": 50, "unit": "ml"},
    ],
    "South Indian Combo": [
        # Ghee Pongal portion here wasn't specified explicitly -- assumed a
        # standard full 250ml portion (its normal stand-alone size) rather
        # than guessing at a fraction. Flag if that's wrong.
        {"refType": "RECIPE", "refName": "Ghee Pongal", "qty": 250, "unit": "ml"},
        {"refType": "RECIPE_MISSING", "refName": "Idly (2 pcs, in South Indian Combo)", "qty": 2, "unit": "piece"},
        {"refType": "RECIPE_MISSING", "refName": "Vada (1 pc, in South Indian Combo)", "qty": 1, "unit": "piece"},
        {"refType": "RECIPE_MISSING", "refName": "Filter Coffee (in South Indian Combo)", "qty": 1, "unit": "piece"},
    ],
}


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

    entries.extend(COMBO_COMPOSITIONS.get(dish_name, []))

    return entries
