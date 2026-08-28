"""
One-time migration: adds the Dish/Recipe/Intent tables for the Intent and
Recipe features. Safe to re-run (CREATE TABLE IF NOT EXISTS everywhere).

Usage:
    .venv/bin/python tools/migrate_add_intent_recipe.py [path-to-db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS Dish (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    departmentId TEXT NOT NULL REFERENCES Department(id),
    category TEXT NOT NULL,
    menuGroup TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS Dish_name_idx ON Dish(name);

CREATE TABLE IF NOT EXISTS DishAlias (
    id TEXT PRIMARY KEY,
    dishId TEXT NOT NULL REFERENCES Dish(id),
    alias TEXT NOT NULL,
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS DishAlias_dishId_idx ON DishAlias(dishId);

CREATE TABLE IF NOT EXISTS Recipe (
    id TEXT PRIMARY KEY,
    dishId TEXT REFERENCES Dish(id),
    name TEXT NOT NULL,
    servesQty REAL,
    servesVolumeLitre REAL,
    portionSizeMl REAL,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS Recipe_dishId_idx ON Recipe(dishId);

CREATE TABLE IF NOT EXISTS RecipeLine (
    id TEXT PRIMARY KEY,
    recipeId TEXT NOT NULL REFERENCES Recipe(id),
    itemId TEXT REFERENCES Item(id),
    subRecipeId TEXT REFERENCES Recipe(id),
    qty REAL NOT NULL,
    rawIngredientName TEXT NOT NULL,
    rawQtyValue REAL NOT NULL,
    rawQtyUnit TEXT NOT NULL,
    matchStatus TEXT NOT NULL DEFAULT 'AUTO',
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS RecipeLine_recipeId_idx ON RecipeLine(recipeId);

CREATE TABLE IF NOT EXISTS DishSaleUpload (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    date TEXT NOT NULL,
    createdAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS DishSale (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    dishId TEXT REFERENCES Dish(id),
    rawItemName TEXT NOT NULL,
    rawCategory TEXT,
    restaurant TEXT,
    qty REAL NOT NULL,
    matchConfidence REAL,
    matchStatus TEXT NOT NULL,
    uploadId TEXT REFERENCES DishSaleUpload(id),
    createdAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS DishSale_date_idx ON DishSale(date);
CREATE INDEX IF NOT EXISTS DishSale_dishId_idx ON DishSale(dishId);

CREATE TABLE IF NOT EXISTS IntentDay (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    branchId TEXT NOT NULL REFERENCES Branch(id),
    status TEXT NOT NULL DEFAULT 'DRAFT',
    confirmedAt TEXT,
    confirmedByUserId TEXT,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS IntentDay_date_branch_idx ON IntentDay(date, branchId);

CREATE TABLE IF NOT EXISTS IntentDishCount (
    id TEXT PRIMARY KEY,
    intentDayId TEXT NOT NULL REFERENCES IntentDay(id),
    dishId TEXT NOT NULL REFERENCES Dish(id),
    predictedQty REAL NOT NULL,
    finalQty REAL NOT NULL,
    source TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS IntentDishCount_intentDayId_idx ON IntentDishCount(intentDayId);

CREATE TABLE IF NOT EXISTS IntentIngredient (
    id TEXT PRIMARY KEY,
    intentDayId TEXT NOT NULL REFERENCES IntentDay(id),
    itemId TEXT NOT NULL REFERENCES Item(id),
    groupLabel TEXT NOT NULL,
    qty REAL NOT NULL,
    source TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS IntentIngredient_intentDayId_idx ON IntentIngredient(intentDayId);
"""


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('Dish','DishAlias','Recipe','RecipeLine','DishSaleUpload','DishSale',"
        "'IntentDay','IntentDishCount','IntentIngredient')"
    )]
    conn.close()
    print(f"Migrated {db_path} -- tables present: {sorted(tables)}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "instance" / "dev.db"
    migrate(target)
