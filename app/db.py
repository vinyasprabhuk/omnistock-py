"""
Thin sqlite3 connection layer. No ORM -- hand-written SQL, so the schema the
code assumes and the schema in dev.db can never silently drift apart.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "instance" / "dev.db"


def _db_path() -> str:
    return os.environ.get("DATABASE_PATH", str(DEFAULT_DB_PATH))


def get_connection() -> sqlite3.Connection:
    """
    A fresh connection with row_factory set for dict-like access and foreign
    keys enforced (SQLite defaults FK enforcement OFF per-connection).
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def new_id() -> str:
    """
    New primary key. Existing rows use Prisma's cuid() format; nothing in the
    app parses or sorts by that format (opaque TEXT throughout), so new rows
    use uuid4 hex -- stdlib, no dependency, equally opaque.
    """
    return uuid.uuid4().hex


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
