"""
Port of src/lib/inventory/matchItem.ts.

Rule-based fuzzy matching (Sorensen-Dice coefficient over character bigrams)
against item names + aliases. Deliberately not AI: fast, free, deterministic,
and easy to reason about when correcting a match.

Confidence bands (spec): >=90 AUTO (still shown for review), 70-89 REVIEW,
<70 MANUAL (forces explicit selection; best guess still attached).
"""
from __future__ import annotations

import re
import sqlite3
from typing import TypedDict

AUTO_THRESHOLD = 90
REVIEW_THRESHOLD = 70

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize(s: str) -> str:
    return _WHITESPACE_RUN.sub(" ", s.strip().upper())


def compare_two_strings(first: str, second: str) -> float:
    """
    Exact port of the `string-similarity` npm package's compareTwoStrings.

    Note the double-normalization with the caller: normalize() above
    collapses whitespace runs to a single space; this function then strips
    ALL whitespace before comparing bigrams. Both steps are required to
    match the original's behavior exactly.
    """
    first = _WHITESPACE_RUN.sub("", first)
    second = _WHITESPACE_RUN.sub("", second)

    if first == second:
        return 1.0  # identical or both empty
    if len(first) < 2 or len(second) < 2:
        return 0.0

    first_bigrams: dict[str, int] = {}
    for i in range(len(first) - 1):
        bg = first[i:i + 2]
        first_bigrams[bg] = first_bigrams.get(bg, 0) + 1

    intersection_size = 0
    for i in range(len(second) - 1):
        bg = second[i:i + 2]
        count = first_bigrams.get(bg, 0)
        if count > 0:
            first_bigrams[bg] = count - 1
            intersection_size += 1

    return (2.0 * intersection_size) / (len(first) + len(second) - 2)


class ItemMatchResult(TypedDict):
    matchedItemId: str | None
    matchedItemName: str | None
    confidence: float
    status: str  # AUTO | REVIEW | MANUAL


def match_item(conn: sqlite3.Connection, extracted_text: str) -> ItemMatchResult:
    # Items in a stable, explicit order (ORDER BY rowid) so the tie-break
    # rule ("first-encountered candidate wins on an exact score tie") is
    # reproducible -- the original TS has no explicit orderBy at all, so its
    # tie-break depends on unspecified DB row order; this pins it down.
    items = conn.execute(
        "SELECT id, name FROM Item WHERE active = 1 ORDER BY rowid ASC"
    ).fetchall()

    target = normalize(extracted_text)
    best: dict | None = None  # {itemId, itemName, score}

    for item in items:
        aliases = conn.execute(
            "SELECT alias FROM ItemAlias WHERE itemId = ? ORDER BY rowid ASC", (item["id"],)
        ).fetchall()
        candidates = [normalize(item["name"])] + [normalize(a["alias"]) for a in aliases]
        for candidate in candidates:
            score = compare_two_strings(target, candidate) * 100
            if best is None or score > best["score"]:
                best = {"itemId": item["id"], "itemName": item["name"], "score": score}

    if best is None:
        return {"matchedItemId": None, "matchedItemName": None, "confidence": 0, "status": "MANUAL"}

    # Math.round-equivalent (round-half-up, not Python's round-half-to-even)
    # to exactly match the original's Math.round(score*100)/100.
    import math
    confidence = math.floor(best["score"] * 100 + 0.5) / 100

    if confidence >= AUTO_THRESHOLD:
        status = "AUTO"
    elif confidence >= REVIEW_THRESHOLD:
        status = "REVIEW"
    else:
        status = "MANUAL"

    return {
        "matchedItemId": best["itemId"], "matchedItemName": best["itemName"],
        "confidence": confidence, "status": status,
    }


def save_alias(conn: sqlite3.Connection, item_id: str, alias: str) -> None:
    """Called when a reviewer corrects a match, to learn it for next time."""
    from app.dates import now_db
    from app.db import new_id

    normalized = normalize(alias)
    existing = conn.execute("SELECT id FROM ItemAlias WHERE alias = ?", (normalized,)).fetchone()
    if existing:
        conn.execute("UPDATE ItemAlias SET itemId = ? WHERE alias = ?", (item_id, normalized))
    else:
        conn.execute(
            "INSERT INTO ItemAlias (id, itemId, alias, createdAt) VALUES (?, ?, ?, ?)",
            (new_id(), item_id, normalized, now_db()),
        )
