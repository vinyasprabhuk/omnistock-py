"""
Applies the recipe-name aliases confirmed in chat for the Wastage/Production
matcher (see app/services/match_recipe.py) -- e.g. logging "SAMBAR" should
match the real "Tamilnadu Sambar" recipe, not the unrelated "Sambar Rice"
dish that scores higher by raw string similarity alone.

Safe to re-run: save_recipe_alias upserts by alias text, so running this
twice just re-confirms the same 5 mappings rather than duplicating rows.

Usage:
    .venv/bin/python tools/seed_recipe_aliases.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.match_recipe import save_recipe_alias  # noqa: E402

ALIASES = [
    ("Ghee Pongal", "PONGAL"),
    ("Kara Kuuzhambu", "KARAKULAMBU"),
    ("White Kurma", "WHITE KURUMA"),
    ("Kurma", "KURUMA"),
    ("Tamilnadu Sambar", "SAMBAR"),
]


def seed(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    applied = 0
    for recipe_name, alias in ALIASES:
        row = conn.execute("SELECT id FROM Recipe WHERE name = ?", (recipe_name,)).fetchone()
        if row is None:
            print(f"SKIP -- no Recipe named {recipe_name!r} yet (has it been uploaded?)")
            continue
        save_recipe_alias(conn, row["id"], alias)
        applied += 1
        print(f'aliased "{alias}" -> {recipe_name}')
    conn.commit()
    conn.close()
    print(f"\nDone -- {applied}/{len(ALIASES)} aliases applied.")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    seed(target)
