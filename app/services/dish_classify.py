"""
Best-guess classification for newly-seen POS dishes.

Two independent jobs, kept as separate fields on Dish -- see the "menu
groups vs. accompaniment rules" conversation this was built from:

- guess_department / guess_dish_category: the existing rule-category
  (DOSA/IDLY/VADA/POORI/SNACKS/CHAAT/MEALS/VARIETY_RICE/OTHER) that decides
  which accompaniment rule fires in intent_rules.py. Unchanged.
- guess_menu_group: a broader, purely organizational grouping shown in the
  Recipe/Intent screens (Dosa, Idly, Sambar, ...) covering every real dish,
  confirmed against the actual menu -- not tied to what triggers a rule.

Both are keyword guesses against the POS category text and the dish name
itself -- a first draft, meant to be corrected once a dish list screen
exists; nothing here is asserted as ground truth.
"""
from __future__ import annotations

_DEPARTMENT_KEYWORDS: list[tuple[str, str]] = [
    ("dosa", "Dosa"),
    ("uthappam", "Dosa"),
    ("idl", "Idly"),
    ("chaat", "Chaat"),
    ("parotta", "Parotta & Chapathi"),
    ("chapat", "Parotta & Chapathi"),
    ("indian bread", "Parotta & Chapathi"),
    ("chinese", "Chinese"),
    ("noodles", "Chinese"),
    ("fried rice", "Chinese"),
    ("juice", "Coffee and Juice"),
    ("beverage", "Coffee and Juice"),
    ("shake", "Coffee and Juice"),
    ("ice cream", "Coffee and Juice"),
    ("falooda", "Coffee and Juice"),
]


def guess_department(pos_category: str) -> str:
    """Falls back to SOUTH INDIAN, OmniStock's largest general tiffin/meals bucket."""
    text = pos_category.lower()
    for keyword, dept in _DEPARTMENT_KEYWORDS:
        if keyword in text:
            return dept
    return "SOUTH INDIAN"


_CATEGORY_RULES: list[tuple[str, str]] = [
    ("dosa", "DOSA"),
    ("uthappam", "DOSA"),
    ("idl", "IDLY"),
    ("pongal", "PONGAL_KARABATH"),
    ("kara bath", "PONGAL_KARABATH"),
    ("karabath", "PONGAL_KARABATH"),
    ("vada", "VADA"),
    ("pani puri", "CHAAT"),
    ("bhel puri", "CHAAT"),
    ("dahi puri", "CHAAT"),
    ("dhahi puri", "CHAAT"),
    ("poori", "POORI"),
    ("batura", "POORI"),
    ("bajji", "SNACKS"),
    ("bonda", "SNACKS"),
    ("bun", "SNACKS"),
    ("goli baje", "SNACKS"),
    ("paniyaram", "SNACKS"),
    ("chaat", "CHAAT"),
    ("kachori", "CHAAT"),
    ("meals", "MEALS"),
    ("thali", "MEALS"),
    ("variety rice", "VARIETY_RICE"),
    ("bisibele", "VARIETY_RICE"),
    ("bisi bele", "VARIETY_RICE"),
    ("curd rice", "VARIETY_RICE"),
    ("sambar rice", "VARIETY_RICE"),
    ("lemon rice", "VARIETY_RICE"),
    ("tamarind rice", "VARIETY_RICE"),
    ("puliyodharai", "VARIETY_RICE"),
]


def guess_dish_category(pos_category: str, item_name: str) -> str:
    text = f"{pos_category} {item_name}".lower()
    for keyword, category in _CATEGORY_RULES:
        if keyword in text:
            return category
    return "OTHER"


# Standalone South Indian side/curry names -- own menu group only when SOLD
# AS ITSELF (exact name match), never when it's just part of a compound dish
# name like "Sambar Vada" or "Sambar Rice" (those stay Vada / Variety Rice).
_STANDALONE_SIDE_NAMES: dict[str, str] = {
    "sambar": "South Indian Curries", "meals sambar": "South Indian Curries",
    "tiffin sambar": "South Indian Curries", "rasam": "South Indian Curries",
    "kootu": "South Indian Curries", "poriyal": "South Indian Curries",
    "kurma": "South Indian Curries", "white kurma": "South Indian Curries",
    "kara kuzhambu": "South Indian Curries", "karakuzhambu": "South Indian Curries",
    "kara kuuzhambu": "South Indian Curries", "vadakari": "South Indian Curries",
    "potato masala": "South Indian Curries", "payasam": "South Indian Curries",
}

_MENU_GROUP_NAME_RULES: list[tuple[str, str]] = [
    ("dosa", "Dosa"), ("uthappam", "Dosa"),
    ("idl", "Idly"),
    ("vada", "Vada"),
    ("poori", "Poori"), ("batura", "Poori"),
    ("pongal", "Pongal & Kara Bath"), ("kara bath", "Pongal & Kara Bath"), ("karabath", "Pongal & Kara Bath"),
    ("bisibele", "Variety Rice"), ("bisi bele", "Variety Rice"), ("curd rice", "Variety Rice"),
    ("sambar rice", "Variety Rice"), ("lemon rice", "Variety Rice"), ("tamarind rice", "Variety Rice"),
    ("puliyodharai", "Variety Rice"),
    ("pani puri", "Chaat"), ("bhel puri", "Chaat"), ("dahi puri", "Chaat"), ("dhahi puri", "Chaat"),
    ("bajji", "Snacks"), ("bonda", "Snacks"), ("mangalore bun", "Snacks"),
    ("goli baje", "Snacks"), ("paniyaram", "Snacks"),
    ("idiyappam", "Pongal & Kara Bath"),
    ("kesari", "Shakes & Desserts"), ("sweet", "Shakes & Desserts"),
    ("combo", "Combos & Specials"), ("mini tiffin", "Combos & Specials"),
]

_MENU_GROUP_CATEGORY_RULES: list[tuple[str, str]] = [
    ("dosa", "Dosa"), ("uthappam", "Dosa"),
    ("idli", "Idly"), ("idly", "Idly"),
    ("chaat", "Chaat"), ("pav bhaji", "Chaat"), ("kachori", "Chaat"),
    ("evening", "Snacks"),
    ("parotta", "Parotta & Bread"), ("chapat", "Parotta & Bread"), ("indian bread", "Parotta & Bread"),
    ("south indian rice bowl", "Variety Rice"), ("hand tossed", "Variety Rice"),
    ("chinese", "Chinese/North Gravies"), ("noodles", "Chinese/North Gravies"),
    ("fried rice", "Chinese/North Gravies"), ("rice bowl", "Chinese/North Gravies"),
    ("gravies", "Chinese/North Gravies"),
    ("tandoori", "Starters"), ("starters", "Starters"),
    ("biryani", "Rice & Biryani"), ("pulao", "Rice & Biryani"),
    ("hot beverage", "Beverages"), ("fresh juice", "Beverages"),
    ("shake", "Shakes & Desserts"), ("falooda", "Shakes & Desserts"),
    ("ice cream", "Shakes & Desserts"), ("sweet", "Shakes & Desserts"),
    ("podi", "Podi & Condiments"),
    ("papad", "Papad & Raita"), ("raita", "Papad & Raita"),
    ("soup", "Soups & Salad"),
    ("lunch", "Meals & Thali"), ("thali", "Meals & Thali"),
    ("tiffin combo", "Combos & Specials"), ("special", "Combos & Specials"),
    ("healthy subscription", "Combos & Specials"), ("misc", "Combos & Specials"),
]


def guess_menu_group(pos_category: str, item_name: str) -> str:
    name = item_name.strip().lower()

    standalone = _STANDALONE_SIDE_NAMES.get(name)
    if standalone:
        return standalone

    for keyword, group in _MENU_GROUP_NAME_RULES:
        if keyword in name:
            return group

    cat = pos_category.strip().lower()
    for keyword, group in _MENU_GROUP_CATEGORY_RULES:
        if keyword in cat:
            return group

    return "Other"
