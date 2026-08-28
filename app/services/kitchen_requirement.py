"""Port of src/lib/actions/kitchenRequirement.ts."""
from __future__ import annotations

import sqlite3

from app.dates import date_key_to_db, now_db, today_key
from app.db import new_id
from app.services import audit, storage
from app.services.departments import find_or_create_department
from app.services.match_item import match_item, save_alias
from app.services.normalize_unit import normalize_unit
from app.parsing.prepare_kitchen_file import prepare_kitchen_file


def upload_kitchen_screenshot(conn: sqlite3.Connection, user_id: str, branch_id: str,
                               file_bytes: bytes, filename: str, mime_type: str,
                               date_key: str | None, force: bool) -> dict:
    date_key = date_key or today_key()
    saved = storage.save(file_bytes, filename)

    if not force:
        existing = conn.execute(
            "SELECT u.id AS uploadId, kr.id AS requirementId FROM Upload u "
            "LEFT JOIN KitchenRequirement kr ON kr.uploadId = u.id "
            "WHERE u.fileHash = ? AND u.branchId = ? ORDER BY u.createdAt DESC LIMIT 1",
            (saved["fileHash"], branch_id),
        ).fetchone()
        if existing:
            return {"duplicate": {"existingUploadId": existing["uploadId"],
                                   "existingRequirementId": existing["requirementId"]}}

    upload_id = new_id()
    conn.execute(
        "INSERT INTO Upload (id, filePath, fileHash, uploadedById, branchId, createdAt) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (upload_id, saved["filePath"], saved["fileHash"], user_id, branch_id, now_db()),
    )
    requirement_id = new_id()
    conn.execute(
        "INSERT INTO KitchenRequirement (id, uploadId, branchId, date, createdAt) VALUES (?, ?, ?, ?, ?)",
        (requirement_id, upload_id, branch_id, date_key_to_db(date_key), now_db()),
    )
    conn.commit()

    prep = prepare_kitchen_file(file_bytes, mime_type, filename)
    if prep["kind"] == "manual":
        return {"requirementId": requirement_id, "manualEntry": True}

    for dept in prep["extraction"]["departments"]:
        department = find_or_create_department(conn, dept["name"])
        for item in dept["items"]:
            normalized = normalize_unit(item["quantity"], item["unit"])
            if normalized["ambiguous"]:
                match = {"matchedItemId": None, "confidence": 0, "status": "MANUAL"}
            else:
                match = match_item(conn, item["raw_item"])
            conn.execute(
                "INSERT INTO KitchenRequirementItem (id, requirementId, departmentId, extractedText, "
                "matchedItemId, qty, unit, confidence, status, createdAt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), requirement_id, department["id"], item["raw_item"], match["matchedItemId"],
                 normalized["qty"], normalized["unit"] or "UNKNOWN", match["confidence"], match["status"], now_db()),
            )
    conn.commit()
    return {"requirementId": requirement_id}


def get_requirement_for_review(conn: sqlite3.Connection, requirement_id: str) -> dict:
    req = conn.execute("SELECT * FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    items = conn.execute(
        "SELECT kri.*, d.name AS departmentName, i.name AS matchedItemName "
        "FROM KitchenRequirementItem kri "
        "JOIN Department d ON d.id = kri.departmentId "
        "LEFT JOIN Item i ON i.id = kri.matchedItemId "
        "WHERE kri.requirementId = ? ORDER BY kri.createdAt ASC",
        (requirement_id,),
    ).fetchall()
    upload = None
    if req["uploadId"]:
        upload = conn.execute("SELECT * FROM Upload WHERE id = ?", (req["uploadId"],)).fetchone()
    return {"requirement": dict(req), "items": [dict(r) for r in items], "upload": dict(upload) if upload else None}


def update_requirement_item(conn: sqlite3.Connection, item_id: str, department_name: str | None,
                             matched_item_id: str | None, qty: float | None, unit: str | None) -> None:
    item = conn.execute(
        "SELECT kri.*, kr.confirmedAt FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId WHERE kri.id = ?", (item_id,)
    ).fetchone()
    if item is None:
        raise ValueError("Item not found")
    if item["confirmedAt"]:
        raise ValueError("Cannot edit a confirmed requirement")

    updates, params = [], []
    if department_name:
        dept = find_or_create_department(conn, department_name)
        updates.append("departmentId = ?"); params.append(dept["id"])
    if matched_item_id is not None:
        if matched_item_id and matched_item_id != item["matchedItemId"]:
            save_alias(conn, matched_item_id, item["extractedText"])
        updates.append("matchedItemId = ?"); params.append(matched_item_id or None)
        updates.append("status = ?"); params.append("MANUAL")
    if qty is not None:
        updates.append("qty = ?"); params.append(qty)
    if unit is not None:
        updates.append("unit = ?"); params.append(unit)

    if updates:
        params.append(item_id)
        conn.execute(f"UPDATE KitchenRequirementItem SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()


def add_manual_requirement_item(conn: sqlite3.Connection, requirement_id: str, department_name: str,
                                 item_text: str, matched_item_id: str | None, qty: float, unit: str) -> None:
    req = conn.execute("SELECT confirmedAt FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["confirmedAt"]:
        raise ValueError("Cannot edit a confirmed requirement")

    department = find_or_create_department(conn, department_name)
    conn.execute(
        "INSERT INTO KitchenRequirementItem (id, requirementId, departmentId, extractedText, "
        "matchedItemId, qty, unit, confidence, status, createdAt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'MANUAL', ?)",
        (new_id(), requirement_id, department["id"], item_text, matched_item_id, qty, unit, now_db()),
    )
    conn.commit()


def delete_requirement_item(conn: sqlite3.Connection, item_id: str) -> None:
    item = conn.execute(
        "SELECT kri.requirementId, kr.confirmedAt FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId WHERE kri.id = ?", (item_id,)
    ).fetchone()
    if item is None:
        raise ValueError("Item not found")
    if item["confirmedAt"]:
        raise ValueError("Cannot edit a confirmed requirement")
    conn.execute("DELETE FROM KitchenRequirementItem WHERE id = ?", (item_id,))
    conn.commit()


def confirm_kitchen_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str) -> None:
    req = conn.execute("SELECT * FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    items = conn.execute("SELECT * FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)).fetchall()

    unmatched = [i for i in items if not i["matchedItemId"]]
    if unmatched:
        raise ValueError(f"{len(unmatched)} row(s) still need an item selected before confirming")

    conn.execute(
        "UPDATE KitchenRequirement SET confirmedById = ?, confirmedAt = ? WHERE id = ?",
        (user_id, now_db(), requirement_id),
    )
    audit.write(conn, user_id, req["branchId"], "KITCHEN_REQUIREMENT_CONFIRMED",
                "KitchenRequirement", requirement_id, {"itemCount": len(items)})
    conn.commit()
