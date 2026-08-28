"""
Port of src/lib/excel/exportWorkbook.ts. Identical sheet names, column
headers/widths, and bold header row to the live app's exports.
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font


def _sheet(wb: Workbook, name: str, columns: list[tuple[str, int]]):
    sheet = wb.create_sheet(name)
    for col_idx, (header, width) in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True)
        sheet.column_dimensions[cell.column_letter].width = width
    return sheet


def _to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_tracker_workbook(date: str, rows: list[dict]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    sheet = _sheet(wb, f"Tracker {date}", [
        ("Item", 24), ("Opening", 12), ("Price", 10), ("Purchase", 12),
        ("Kitchen Requirement", 18), ("Issued", 12), ("Closing", 12),
        ("Unit", 10), ("Usage Cost", 14),
    ])
    for r in rows:
        sheet.append([
            r["itemName"], r["opening"], r["price"], r["purchased"],
            r["kitchenRequirement"], r["issued"], r["closing"], r["unit"], r["usageCost"],
        ])
    return _to_bytes(wb)


def build_master_inventory_workbook(rows: list[dict]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    sheet = _sheet(wb, "Master Inventory", [
        ("Item Name", 24), ("Unit", 10), ("Price", 10), ("Opening Stock", 14),
        ("Total Purchased", 16), ("Kitchen Requirement", 18), ("Total Issued", 14),
        ("Current Stock", 14), ("Usage Cost", 14), ("Store Value", 14),
    ])
    for r in rows:
        sheet.append([
            r["itemName"], r["unit"], r["purchasePrice"], r["opening"], r["totalPurchased"],
            r["totalKitchenRequirement"], r["totalIssued"], r["currentStock"], r["usageCost"], r["storeValue"],
        ])
    return _to_bytes(wb)


def build_consolidated_requirement_workbook(date: str, rows: list[dict]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    sheet = _sheet(wb, f"Requirement {date}", [
        ("Item", 24), ("Unit", 10), ("Total", 12), ("Department Breakdown", 50),
    ])
    for r in rows:
        breakdown = ", ".join(f"{d['departmentName']}: {d['qty']}" for d in r["byDepartment"])
        sheet.append([r["itemName"], r["unit"], r["total"], breakdown])
    return _to_bytes(wb)
