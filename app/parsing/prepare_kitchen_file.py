"""Port of src/lib/parsing/prepareKitchenFile.ts -- the single dispatch point
deciding how each accepted file type becomes a KitchenRequirementExtraction.
No AI/vision path anywhere: a photo/PDF is kept for reference but never read
automatically -- the review screen opens empty for manual entry."""
from __future__ import annotations

from typing import TypedDict

from app.parsing.kitchen_excel import KitchenRequirementExtraction, parse_kitchen_excel
from app.parsing.kitchen_word import parse_kitchen_word

EXCEL_TYPES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"}
WORD_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"}


class StructuredResult(TypedDict):
    kind: str  # "structured"
    extraction: KitchenRequirementExtraction


class ManualResult(TypedDict):
    kind: str  # "manual"


def prepare_kitchen_file(file_bytes: bytes, mime_type: str, file_name: str) -> dict:
    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""

    if mime_type in EXCEL_TYPES or ext in ("xlsx", "xls"):
        return {"kind": "structured", "extraction": parse_kitchen_excel(file_bytes)}
    if mime_type in WORD_TYPES or ext in ("docx", "doc"):
        return {"kind": "structured", "extraction": parse_kitchen_word(file_bytes)}
    return {"kind": "manual"}
