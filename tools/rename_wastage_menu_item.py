"""
Renames every WastageMenuItem row with a given name (there's often one per
meal period, e.g. "B. SAMBAR" in both Breakfast and Dinner) to a new name.
Only renames the menu button label -- historical Wastage/ProductionLog
entries already logged under the old name keep their original description
text untouched, since that's what was actually logged at the time.

Matches the app's existing uppercase-storage convention for this table
(see admin_service.create_wastage_menu_item), so the new name is stored
uppercased regardless of how it's typed here.

Usage:
    .venv/bin/python tools/rename_wastage_menu_item.py "B. SAMBAR" "Bengaluru Sambar" [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def rename(db_path: Path, old_name: str, new_name: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    old_name = old_name.strip().upper()
    new_name = new_name.strip().upper()

    rows = conn.execute(
        "SELECT id, mealPeriod FROM WastageMenuItem WHERE name = ?", (old_name,)
    ).fetchall()
    if not rows:
        conn.close()
        print(f"No WastageMenuItem rows found named {old_name!r} in {db_path}")
        return

    conn.execute("UPDATE WastageMenuItem SET name = ? WHERE name = ?", (new_name, old_name))
    conn.commit()
    conn.close()
    meal_periods = ", ".join(r["mealPeriod"] for r in rows)
    print(f"Renamed {len(rows)} row(s) ({meal_periods}) from {old_name!r} to {new_name!r} in {db_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    old, new = sys.argv[1], sys.argv[2]
    target = Path(sys.argv[3]) if len(sys.argv) > 3 else BASE_DIR / "instance" / "dev.db"
    rename(target, old, new)
