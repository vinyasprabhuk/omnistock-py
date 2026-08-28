"""
Port of src/lib/settings/branding.ts.

Singleton AppSettings row (id='singleton'), lazily created via upsert on
first admin edit -- no seed migration required.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import TypedDict

from app.dates import now_db

THEME_COLORS = ["navy", "neutral", "blue", "green", "rose", "orange", "purple"]
THEME_MODES = ["light", "dark", "system"]
BRAND_SIZES = ["sm", "md", "lg"]

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Branding(TypedDict):
    appName: str
    tagline: str | None
    logoPath: str | None
    headerColor: str | None
    accentColor: str | None
    themeColor: str
    themeMode: str
    brandSize: str


def get_branding(conn: sqlite3.Connection) -> Branding:
    row = conn.execute("SELECT * FROM AppSettings WHERE id = 'singleton'").fetchone()
    theme_color = row["themeColor"] if row and row["themeColor"] in THEME_COLORS else "navy"
    theme_mode = row["themeMode"] if row and row["themeMode"] in THEME_MODES else "system"
    brand_size = row["brandSize"] if row and row["brandSize"] in BRAND_SIZES else "md"
    return {
        "appName": (row["appName"] if row else None) or "OmniStock",
        "tagline": row["tagline"] if row else None,
        "logoPath": row["logoPath"] if row else None,
        "headerColor": row["headerColor"] if row else None,
        "accentColor": row["accentColor"] if row else None,
        "themeColor": theme_color,
        "themeMode": theme_mode,
        "brandSize": brand_size,
    }


def _upsert(conn: sqlite3.Connection, fields: dict) -> None:
    existing = conn.execute("SELECT id FROM AppSettings WHERE id = 'singleton'").fetchone()
    if existing:
        set_clause = ", ".join(f'"{k}" = ?' for k in fields)
        conn.execute(
            f'UPDATE AppSettings SET {set_clause}, updatedAt = ? WHERE id = \'singleton\'',
            [*fields.values(), now_db()],
        )
    else:
        cols = ", ".join(f'"{k}"' for k in fields)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f'INSERT INTO AppSettings (id, {cols}, updatedAt) VALUES (\'singleton\', {placeholders}, ?)',
            [*fields.values(), now_db()],
        )
    conn.commit()


def update_header_color(conn: sqlite3.Connection, raw: str, reset: bool) -> None:
    header_color = None if reset else raw.strip()
    if header_color is not None and not HEX_COLOR_RE.match(header_color):
        raise ValueError("Invalid color")
    _upsert(conn, {"headerColor": header_color})


def update_accent_color(conn: sqlite3.Connection, raw: str, reset: bool) -> None:
    accent_color = None if reset else raw.strip()
    if accent_color is not None and not HEX_COLOR_RE.match(accent_color):
        raise ValueError("Invalid color")
    _upsert(conn, {"accentColor": accent_color})


def update_theme(conn: sqlite3.Connection, theme_color: str, theme_mode: str, brand_size: str) -> None:
    if theme_color not in THEME_COLORS:
        raise ValueError("Invalid theme color")
    if theme_mode not in THEME_MODES:
        raise ValueError("Invalid theme mode")
    if brand_size not in BRAND_SIZES:
        raise ValueError("Invalid brand size")
    _upsert(conn, {"themeColor": theme_color, "themeMode": theme_mode, "brandSize": brand_size})


def update_app_name(conn: sqlite3.Connection, app_name: str, tagline: str) -> None:
    app_name = app_name.strip()
    if not app_name:
        raise ValueError("App name cannot be empty")
    tagline = tagline.strip()
    _upsert(conn, {"appName": app_name, "tagline": tagline or None})


def update_logo(conn: sqlite3.Connection, static_dir: Path, filename: str, file_bytes: bytes) -> None:
    """
    Writes to static/branding/logo.<ext> and stores a `/branding/<file>?v=...`
    DB path -- served by the dedicated /branding/<filename> route (app/views/
    files.py), matching the path convention already present in the live DB
    (e.g. existing rows already say "/branding/logo.png?v=...").
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "png").lower()
    branding_dir = static_dir / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"logo.{ext}"
    (branding_dir / out_name).write_bytes(file_bytes)

    logo_path = f"/branding/{out_name}?v={int(time.time() * 1000)}"
    _upsert(conn, {"logoPath": logo_path})
