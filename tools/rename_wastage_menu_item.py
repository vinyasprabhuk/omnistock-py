"""
Renames every WastageMenuItem row with a given name (there's often one per
meal period, e.g. "B. SAMBAR" in both Breakfast and Dinner) to a new name.
Only renames the menu button label -- historical Wastage/ProductionLog
entries already logged under the old name keep their original description
text untouched, since that's what was actually logged at the time.

Matches the app's existing uppercase-storage convention for this table
(see admin_service.create_wastage_menu_item), so the new name is stored
uppercased regardless of how it's typed here.

Renames every meal period's row by default (there's often one "SAMBAR"
row per meal period, and this renames all of them) -- pass --meal to
scope it to just one, e.g. when Lunch's "Sambar" should become "Meals
Sambar" while Breakfast/Dinner's plain "Sambar" stays as-is.

Usage:
    .venv/bin/python tools/rename_wastage_menu_item.py "B. SAMBAR" "Bengaluru Sambar" [path-to-db]
    .venv/bin/python tools/rename_wastage_menu_item.py "SAMBAR" "Meals Sambar" --meal LUNCH [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MEAL_PERIODS = ("BREAKFAST", "LUNCH", "DINNER")


def rename(db_path: Path, old_name: str, new_name: str, meal_period: str | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    old_name = old_name.strip().upper()
    new_name = new_name.strip().upper()

    query = "SELECT id, mealPeriod FROM WastageMenuItem WHERE name = ?"
    params: list = [old_name]
    if meal_period:
        query += " AND mealPeriod = ?"
        params.append(meal_period)

    rows = conn.execute(query, params).fetchall()
    if not rows:
        conn.close()
        scope = f" in {meal_period}" if meal_period else ""
        print(f"No WastageMenuItem rows found named {old_name!r}{scope} in {db_path}")
        return

    update_query = "UPDATE WastageMenuItem SET name = ? WHERE name = ?"
    update_params: list = [new_name, old_name]
    if meal_period:
        update_query += " AND mealPeriod = ?"
        update_params.append(meal_period)
    conn.execute(update_query, update_params)
    conn.commit()
    conn.close()
    meal_periods = ", ".join(r["mealPeriod"] for r in rows)
    print(f"Renamed {len(rows)} row(s) ({meal_periods}) from {old_name!r} to {new_name!r} in {db_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    meal = None
    if "--meal" in args:
        i = args.index("--meal")
        meal = args[i + 1].strip().upper()
        if meal not in MEAL_PERIODS:
            print(f"--meal must be one of {MEAL_PERIODS}, got {meal!r}")
            sys.exit(1)
        del args[i:i + 2]

    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    old, new = args[0], args[1]
    target = Path(args[2]) if len(args) > 2 else BASE_DIR / "instance" / "dev.db"
    rename(target, old, new, meal)
