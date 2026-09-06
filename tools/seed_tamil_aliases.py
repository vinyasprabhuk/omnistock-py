"""
One-time (but safe to re-run) seed of common Tamil spoken names as
ItemAlias rows, so the Opening Stock voice-match feature (and any other
caller of match_item) recognizes them alongside the English item name --
e.g. saying "vellam" matches "Jaggery".

Deliberately conservative: only includes terms this script's author was
genuinely confident about (common, unambiguous Tamil culinary
vocabulary) -- skips anything ambiguous (e.g. a term that could mean
either of two different items) rather than guess and risk a wrong
match. Add more via Admin -> Item Master -> Add alias as real usage
surfaces them; this is a starting point, not a complete dictionary.

Uses save_alias() (the same upsert match_item.py already uses when a
reviewer corrects a match), so re-running this is harmless -- an
already-seeded alias just gets its itemId re-confirmed, not duplicated.

Usage:
    .venv/bin/python tools/seed_tamil_aliases.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.match_item import save_alias  # noqa: E402

# item name (must match Item.name exactly) -> list of Tamil alias(es)
ALIASES: dict[str, list[str]] = {
    "Jaggery": ["vellam"],
    "Sugar": ["sakkarai"],
    "Salt": ["uppu"],
    "Rock Salt": ["kal uppu"],
    "Turmeric Powder": ["manjal podi", "manjal thool"],
    "Chilly Powder": ["milagai thool", "molaga podi"],
    "Red Chilli": ["sivappu milagai"],
    "Black pepper powder": ["milagu podi"],
    "Pepper": ["milagu"],
    "Coriander Powder": ["kothamalli podi"],
    "Coriander whole": ["kothamalli"],
    "Garlic": ["poondu"],
    "Butter": ["vennai"],
    "Ghee": ["nei"],
    "Cardamom": ["yelakkai", "elakkai"],
    "Cloves": ["krambu", "lavangam"],
    "Cinnamon": ["pattai"],
    "Fenugreek": ["vendhayam"],
    "Mustard": ["kadugu"],
    "Mustard Oil": ["kadugu ennai"],
    "Coconut oil": ["thengai ennai"],
    "Gingely oil": ["nallennai"],
    "Curd": ["thayir"],
    "Milk": ["paal"],
    "Coffee": ["kaapi"],
    "Tamarind": ["puli"],
    "Honey": ["thean"],
    "Green Peas": ["pattani"],
    "Green Gram": ["pachai payaru"],
    "Moong Dhal": ["pasi paruppu"],
    "Toor Dhal": ["thuvaram paruppu"],
    "Chana Dhal": ["kadalai paruppu"],
    "Urid Dhal": ["ulundu paruppu"],
    "White Channa": ["vellai kadalai"],
    "fried gram": ["pottukadalai"],
    "groundnut": ["verkadalai"],
    "Besan Flour": ["kadalai maavu"],
    "Rice Flour": ["arisi maavu"],
    "Idly Rice": ["idli arisi"],
    "Raw Rice": ["pacharisi"],
    "Jeera": ["seeragam", "jeeragam"],
    "Jeera Powder": ["seeragam podi"],
    "Cashew": ["mundhiri"],
}


def seed(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    added, missing_items = 0, []
    for item_name, aliases in ALIASES.items():
        row = conn.execute("SELECT id FROM Item WHERE name = ? AND active = 1", (item_name,)).fetchone()
        if row is None:
            missing_items.append(item_name)
            continue
        for alias in aliases:
            save_alias(conn, row["id"], alias)
            added += 1
    conn.commit()
    conn.close()

    print(f"Seeded {added} alias(es) across {len(ALIASES) - len(missing_items)} item(s).")
    if missing_items:
        print(f"Skipped {len(missing_items)} item name(s) not found in this Item Master: {missing_items}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    seed(target)
