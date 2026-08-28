"""
Loads a parsed day-wise POS sale file into DishSale rows, matching each raw
item name against the Dish catalog (auto-creating a new Dish, best-guess
classified, the first time a genuinely new item is seen -- see
dish_classify.py) the same way Kitchen Requirement upload auto-attaches to
Item Master rather than blocking on an exhaustive pre-built catalog.
"""
from __future__ import annotations

import sqlite3

from app.db import new_id
from app.dates import date_key_to_db, now_db
from app.parsing.dish_sales_excel import parse_dish_sales_file
from app.services.dish_classify import guess_department, guess_dish_category, guess_menu_group
from app.services.match_dish import match_dish


def _get_or_create_dish(conn: sqlite3.Connection, name: str, pos_category: str) -> str:
    match = match_dish(conn, name)
    if match["status"] == "AUTO" and match["matchedDishId"]:
        return match["matchedDishId"]

    existing = conn.execute("SELECT id FROM Dish WHERE name = ?", (name,)).fetchone()
    if existing:
        return existing["id"]

    dept_name = guess_department(pos_category)
    dept = conn.execute("SELECT id FROM Department WHERE name = ?", (dept_name,)).fetchone()
    if dept is None:
        dept = conn.execute("SELECT id FROM Department WHERE name = 'SOUTH INDIAN'").fetchone()
    category = guess_dish_category(pos_category, name)
    menu_group = guess_menu_group(pos_category, name)

    dish_id = new_id()
    ts = now_db()
    conn.execute(
        "INSERT INTO Dish (id, name, departmentId, category, menuGroup, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (dish_id, name, dept["id"], category, menu_group, ts, ts),
    )
    return dish_id


def load_dish_sales_file(conn: sqlite3.Connection, path: str, filename: str) -> dict:
    rows = parse_dish_sales_file(path)
    if not rows:
        return {"date": None, "rowsLoaded": 0, "dishesCreated": 0}

    date_key = rows[0]["date"]
    date_db = date_key_to_db(date_key)

    existing_upload = conn.execute(
        "SELECT id FROM DishSaleUpload WHERE date = ?", (date_db,)
    ).fetchone()
    if existing_upload:
        conn.execute("DELETE FROM DishSale WHERE uploadId = ?", (existing_upload["id"],))
        upload_id = existing_upload["id"]
    else:
        upload_id = new_id()
        conn.execute(
            "INSERT INTO DishSaleUpload (id, filename, date, createdAt) VALUES (?, ?, ?, ?)",
            (upload_id, filename, date_db, now_db()),
        )

    dishes_before = conn.execute("SELECT COUNT(*) c FROM Dish").fetchone()["c"]
    loaded = 0
    for r in rows:
        dish_id = _get_or_create_dish(conn, r["item"], r["category"])
        match = match_dish(conn, r["item"])
        conn.execute(
            "INSERT INTO DishSale (id, date, dishId, rawItemName, rawCategory, restaurant, qty, "
            "matchConfidence, matchStatus, uploadId, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), date_db, dish_id, r["item"], r["category"], r["restaurant"], r["qty"],
             match["confidence"], match["status"], upload_id, now_db()),
        )
        loaded += 1
    dishes_after = conn.execute("SELECT COUNT(*) c FROM Dish").fetchone()["c"]

    return {"date": date_key, "rowsLoaded": loaded, "dishesCreated": dishes_after - dishes_before}
