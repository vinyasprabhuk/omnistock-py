"""
Port of src/lib/parsing/parseKitchenWord.ts.

The original converts the docx to HTML via `mammoth` (chosen there because it
preserves table structure) and walks paragraphs/tables in document order: a
paragraph's text becomes the "current department" until a table is hit,
whose rows are read as repeating (S.No, Item, Qty) column groups.

This port reads the docx's OOXML directly (stdlib zipfile + ElementTree)
instead of going through mammoth/HTML -- avoids a `python-docx`/`lxml`
dependency (a C extension, exactly the class of thing this rewrite exists to
avoid) and is actually more correct than the original's regex-based HTML
entity unescaping, since ElementTree decodes XML entities properly. Same
algorithm, same constants, walking <w:p>/<w:tbl> elements in document order
instead of <p>/<table> HTML tags.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from typing import TypedDict

_WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_QTY_UNIT_RE = re.compile(r"^([\d.]+)\s*([A-Za-z]*)$")

HEADER_TOKENS = {"S.NO", "SNO", "S NO", "SL.NO", "ITEM", "QTY"}


class ExtractedItem(TypedDict):
    raw_item: str
    quantity: float
    unit: str | None


class ExtractedDepartment(TypedDict):
    name: str
    items: list[ExtractedItem]


class KitchenRequirementExtraction(TypedDict):
    departments: list[ExtractedDepartment]


def _paragraph_text(p_elem) -> str:
    return "".join(t.text or "" for t in p_elem.iter(f"{_WNS}t")).strip()


def _cell_text(tc_elem) -> str:
    return "".join(t.text or "" for t in tc_elem.iter(f"{_WNS}t")).strip()


def _parse_qty_unit(text: str) -> dict:
    match = _QTY_UNIT_RE.match(text.strip())
    if not match:
        return {"qty": float("nan"), "unit": None}
    unit = match.group(2).upper() if match.group(2) else None
    return {"qty": float(match.group(1)), "unit": unit}


def _local_tag(elem) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def parse_kitchen_word(file_bytes: bytes) -> KitchenRequirementExtraction:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_WNS}body")
    if body is None:
        return {"departments": []}

    departments_map: dict[str, ExtractedDepartment] = {}
    current_dept: str | None = None

    def get_dept(name: str) -> ExtractedDepartment:
        key = name.strip().upper()
        return departments_map.setdefault(key, {"name": name.strip(), "items": []})

    for child in body:
        tag = _local_tag(child)

        if tag == "p":
            text = _paragraph_text(child)
            if text and text.upper() not in HEADER_TOKENS:
                current_dept = text
            continue

        if tag == "tbl":
            for tr in child.iter(f"{_WNS}tr"):
                cells = [_cell_text(tc) for tc in tr.findall(f"{_WNS}tc")]
                if all((c.upper() in HEADER_TOKENS or c == "") for c in cells):
                    continue  # column-header row

                i = 0
                while i + 2 < len(cells) + 1 and i + 1 < len(cells):
                    item_text = cells[i + 1] if i + 1 < len(cells) else ""
                    qty_text = cells[i + 2] if i + 2 < len(cells) else ""
                    i += 3
                    if not item_text or not qty_text:
                        continue
                    if not current_dept:
                        continue
                    parsed = _parse_qty_unit(qty_text)
                    qty = parsed["qty"]
                    get_dept(current_dept)["items"].append({
                        "raw_item": item_text,
                        "quantity": 0 if qty != qty else qty,  # NaN check
                        "unit": parsed["unit"],
                    })

    return {"departments": list(departments_map.values())}
