"""
One-time data seed: adds 33 vegetables/fruits to Item Master that were
missing from both Item Master and the Daily Tracker, with purchase prices
averaged (qty-weighted) from 4 real vendor bills. Safe to re-run -- skips
any name that already exists.

Usage:
    .venv/bin/python tools/add_vegetable_items.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.admin import create_item  # noqa: E402

ITEMS: list[tuple[str, float]] = [
    ("Apple", 240.00),
    ("Beans", 106.29),
    ("Bottle Gourd (Suraikkai)", 42.00),
    ("Brinjal", 50.00),
    ("Cabbage", 40.00),
    ("Capsicum Red", 103.33),
    ("Capsicum Yellow", 103.33),
    ("Cauliflower", 43.00),
    ("Celery", 40.00),
    ("Cucumber", 46.00),
    ("Drumstick", 23.00),
    ("Ginger", 77.73),
    ("Lady's Finger", 26.00),
    ("Lemon", 113.00),
    ("Mint Leaves", 17.00),
    ("Musk Melon", 50.00),
    ("Onion", 177.78),
    ("Orange", 78.00),
    ("Palak", 42.00),
    ("Pineapple", 80.00),
    ("Pomegranate", 213.67),
    ("Potato", 104.00),
    ("Pumpkin Red", 84.00),
    ("Raw Mango", 16.00),
    ("Sambar Onion", 42.00),
    ("Sathukudi", 74.00),
    ("Snack Gourd", 75.00),
    ("Snake Gourd (Pudalangai)", 74.00),
    ("Spring Onion", 26.00),
    ("Tomato Hybrid", 150.00),
    ("Watermelon", 90.20),
    ("Yam (Karunai Kizhangu)", 156.00),
    ("Zucchini (Seemai Surakkai)", 42.00),
]


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    branch_row = conn.execute("SELECT id FROM Branch LIMIT 1").fetchone()
    if branch_row is None:
        conn.close()
        raise RuntimeError(f"No Branch row found in {db_path} -- nothing to attach opening stock to")
    branch_id = branch_row["id"]

    created, skipped = [], []
    for name, price in ITEMS:
        existing = conn.execute("SELECT id FROM Item WHERE name = ?", (name,)).fetchone()
        if existing:
            skipped.append(name)
            continue
        create_item(conn, name, "KG", price, 0, branch_id, None)
        created.append(name)

    conn.close()
    print(f"Migrated {db_path} -- created {len(created)}, skipped (already present) {len(skipped)}")
    if created:
        print("Created: " + ", ".join(created))
    if skipped:
        print("Skipped: " + ", ".join(skipped))


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
