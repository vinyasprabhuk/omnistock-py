"""Port of src/lib/actions/admin.ts."""
from __future__ import annotations

import sqlite3

from app.dates import now_db
from app.db import new_id
from app.security import hash_password


def create_item(conn: sqlite3.Connection, name: str, unit: str, purchase_price: float,
                 opening_stock: float, branch_id: str, category: str | None) -> str:
    item_id = new_id()
    conn.execute(
        "INSERT INTO Item (id, name, unit, purchasePrice, category, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (item_id, name.strip(), unit.strip(), purchase_price, category or None, now_db(), now_db()),
    )
    if opening_stock:
        conn.execute(
            "INSERT INTO ItemOpeningStock (id, itemId, branchId, qty, updatedAt) VALUES (?, ?, ?, ?, ?)",
            (new_id(), item_id, branch_id, opening_stock, now_db()),
        )
    conn.commit()
    return item_id


def set_opening_stock(conn: sqlite3.Connection, item_id: str, branch_id: str, qty: float) -> None:
    existing = conn.execute(
        "SELECT id FROM ItemOpeningStock WHERE itemId = ? AND branchId = ?", (item_id, branch_id)
    ).fetchone()
    if existing:
        conn.execute("UPDATE ItemOpeningStock SET qty = ?, updatedAt = ? WHERE id = ?", (qty, now_db(), existing["id"]))
    else:
        conn.execute(
            "INSERT INTO ItemOpeningStock (id, itemId, branchId, qty, updatedAt) VALUES (?, ?, ?, ?, ?)",
            (new_id(), item_id, branch_id, qty, now_db()),
        )
    conn.commit()


def deactivate_item(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute("UPDATE Item SET active = 0, updatedAt = ? WHERE id = ?", (now_db(), item_id))
    conn.commit()


def add_item_alias(conn: sqlite3.Connection, item_id: str, alias: str) -> None:
    alias = alias.strip().upper()
    existing = conn.execute("SELECT id FROM ItemAlias WHERE alias = ?", (alias,)).fetchone()
    if existing:
        conn.execute("UPDATE ItemAlias SET itemId = ? WHERE alias = ?", (item_id, alias))
    else:
        conn.execute(
            "INSERT INTO ItemAlias (id, itemId, alias, createdAt) VALUES (?, ?, ?, ?)",
            (new_id(), item_id, alias, now_db()),
        )
    conn.commit()


def create_branch(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT INTO Branch (id, name, active, createdAt, updatedAt) VALUES (?, ?, 1, ?, ?)",
        (new_id(), name.strip(), now_db(), now_db()),
    )
    conn.commit()


def rename_branch(conn: sqlite3.Connection, branch_id: str, name: str) -> None:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Branch name cannot be empty")
    conn.execute("UPDATE Branch SET name = ?, updatedAt = ? WHERE id = ?", (trimmed, now_db(), branch_id))
    conn.commit()


def create_department(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("INSERT INTO Department (id, name, active) VALUES (?, ?, 1)", (new_id(), name.strip()))
    conn.commit()


def delete_department(conn: sqlite3.Connection, department_id: str) -> None:
    item_count = conn.execute(
        "SELECT COUNT(*) FROM KitchenRequirementItem WHERE departmentId = ?", (department_id,)
    ).fetchone()[0]
    if item_count > 0:
        raise ValueError(f"Can't delete -- {item_count} kitchen requirement item(s) still reference this department")
    issue_count = conn.execute(
        "SELECT COUNT(*) FROM StockIssue WHERE departmentId = ?", (department_id,)
    ).fetchone()[0]
    if issue_count > 0:
        raise ValueError(f"Can't delete -- {issue_count} stock issue(s) still reference this department")
    conn.execute("DELETE FROM Department WHERE id = ?", (department_id,))
    conn.commit()


def create_user(conn: sqlite3.Connection, name: str, email: str, password: str,
                 role: str, branch_id: str | None) -> None:
    password_hash = hash_password(password)
    conn.execute(
        "INSERT INTO User (id, name, email, passwordHash, role, branchId, active, createdAt, updatedAt) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (new_id(), name.strip(), email.strip().lower(), password_hash, role,
         None if role == "ADMIN" else branch_id, now_db(), now_db()),
    )
    conn.commit()


def deactivate_user(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute("UPDATE User SET active = 0, updatedAt = ? WHERE id = ?", (now_db(), user_id))
    conn.commit()


def reset_user_password(conn: sqlite3.Connection, user_id: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters")
    conn.execute(
        "UPDATE User SET passwordHash = ?, updatedAt = ? WHERE id = ?",
        (hash_password(new_password), now_db(), user_id),
    )
    conn.commit()
