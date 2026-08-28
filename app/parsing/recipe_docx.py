"""
Parser for the "Moksham Recipe" Word document -- one Word table per recipe,
holding its ingredient list as [name, qty] row pairs, bracketed by plain
paragraphs (Recipe Name / Category / Serving Size / Portion Size / Prep-Cook
time). Recipes are split on "Recipe Name" paragraph markers, processing
`w:body`'s direct children (a mix of `w:p` and `w:tbl`) IN DOCUMENT ORDER --
not via a flat `.iter()` paragraph dump, since header text and the
ingredient table are siblings, and getting their relative order right is
what correctly excludes a trailing note paragraph (e.g. "Kurma" after Curd
Rice's table) from being read as an ingredient.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from typing import TypedDict

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_QTY_RE = re.compile(r"^\s*([\d.]+)\s*([A-Za-z]+)?\s*$")
_SERVES_RE = re.compile(
    r"Serves:\s*([\d.]+)\s*pax(?:\s*,?\s*\(?\s*([\d.]+)\s*(?:litres?|litre|ltr)\s*\)?)?",
    re.IGNORECASE,
)
_PORTION_RE = re.compile(r"Portion Size:\s*([\d.]+)\s*(ml|grams?|kg)", re.IGNORECASE)


class RecipeIngredientLine(TypedDict):
    ingredientName: str
    qtyValue: float
    qtyUnit: str  # raw unit word from the doc: grams, ml, kg, pieces, ...


class ParsedRecipe(TypedDict):
    name: str
    category: str
    servesQty: float | None
    servesVolumeLitre: float | None
    portionSizeMl: float | None
    ingredients: list[RecipeIngredientLine]


def _cell_text(tc: ET.Element) -> str:
    return "".join(t.text or "" for t in tc.iter(f"{W}t")).strip()


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{W}t")).strip()


def _parse_qty(raw: str) -> tuple[float, str] | None:
    m = _QTY_RE.match(raw.strip())
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").strip().lower()
    return value, unit


def parse_recipe_docx(path: str) -> list[ParsedRecipe]:
    with zipfile.ZipFile(path) as z:
        xml_bytes = z.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find(f"{W}body")
    if body is None:
        return []

    blocks: list[list[ET.Element]] = []
    current: list[ET.Element] = []
    for child in list(body):
        tag = child.tag.split("}")[-1]
        if tag == "p" and _para_text(child).strip() == "Recipe Name":
            if current:
                blocks.append(current)
            current = [child]
        else:
            current.append(child)
    if current:
        blocks.append(current)
    # Drop anything before the first "Recipe Name" marker (title-page cruft).
    blocks = [b for b in blocks if b and _para_text(b[0]).strip() == "Recipe Name"]

    recipes: list[ParsedRecipe] = []
    for block in blocks:
        paras = [(_para_text(c), c) for c in block if c.tag.split("}")[-1] == "p"]
        lines = [t for t, _ in paras if t.strip()]
        tables = [c for c in block if c.tag.split("}")[-1] == "tbl"]

        name = lines[1] if len(lines) > 1 else ""
        category = ""
        serves_qty: float | None = None
        serves_volume: float | None = None
        portion_ml: float | None = None
        for i, line in enumerate(lines):
            if line.strip() == "Category" and i + 1 < len(lines):
                category = lines[i + 1]
            m = _SERVES_RE.search(line)
            if m:
                serves_qty = float(m.group(1))
                if m.group(2):
                    serves_volume = float(m.group(2))
            m2 = _PORTION_RE.search(line)
            if m2:
                val, unit = float(m2.group(1)), m2.group(2).lower()
                portion_ml = val if unit == "ml" else (val * 1000 if unit in ("kg",) else val)

        ingredients: list[RecipeIngredientLine] = []
        for tbl in tables:
            for tr in tbl.findall(f"{W}tr"):
                cells = [_cell_text(tc) for tc in tr.findall(f"{W}tc")]
                if len(cells) < 2 or not cells[0]:
                    continue
                parsed = _parse_qty(cells[1])
                if parsed is None:
                    continue
                value, unit = parsed
                ingredients.append({
                    "ingredientName": cells[0].strip(),
                    "qtyValue": value,
                    "qtyUnit": unit,
                })

        recipes.append({
            "name": name.strip(),
            "category": category.strip(),
            "servesQty": serves_qty,
            "servesVolumeLitre": serves_volume,
            "portionSizeMl": portion_ml,
            "ingredients": ingredients,
        })

    return recipes
