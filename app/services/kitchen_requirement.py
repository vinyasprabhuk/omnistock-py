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


def create_manual_requirement(conn: sqlite3.Connection, user_id: str, branch_id: str,
                               date_key: str, lines: list[dict]) -> str:
    """
    Skip-the-file path: user picks real items directly from a dropdown (no
    OCR/text-matching involved at all, since there's no extracted text to
    match against) and enters quantities themselves. Each line already
    carries a confirmed itemId, so every row is created at AUTO/100
    confidence -- there's nothing to "review" in the matching sense, though
    the requirement still opens on the review screen so admin can double
    check quantities/departments and add more before confirming.

    lines: [{"departmentName": str, "itemId": str, "qty": float}, ...]
    Matches KitchenRequirement's schema-documented uploadId=NULL case
    ("manual entry fallback -- no upload").
    """
    if not lines:
        raise ValueError("Add at least one item")

    requirement_id = new_id()
    conn.execute(
        "INSERT INTO KitchenRequirement (id, uploadId, branchId, date, createdAt) VALUES (?, NULL, ?, ?, ?)",
        (requirement_id, branch_id, date_key_to_db(date_key), now_db()),
    )
    for line in lines:
        item = conn.execute("SELECT name, unit FROM Item WHERE id = ?", (line["itemId"],)).fetchone()
        if item is None:
            continue
        department = find_or_create_department(conn, line["departmentName"])
        conn.execute(
            "INSERT INTO KitchenRequirementItem (id, requirementId, departmentId, extractedText, "
            "matchedItemId, qty, unit, confidence, status, createdAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 100, 'AUTO', ?)",
            (new_id(), requirement_id, department["id"], item["name"], line["itemId"],
             line["qty"], item["unit"], now_db()),
        )
    conn.commit()
    return requirement_id


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


def get_pending_requirements(conn: sqlite3.Connection, user: dict) -> list[dict]:
    """Uploaded-but-not-yet-confirmed requirements needing admin/manager
    review, scoped to the user's branch (or every branch for a
    not-branch-locked admin). Backs both the Kitchen Upload page's
    'Pending Review' list and the nav badge count."""
    if user is None or user["role"] not in ("ADMIN", "MANAGER"):
        return []
    conditions = ["kr.confirmedAt IS NULL"]
    params: list = []
    if user.get("branchId"):
        conditions.append("kr.branchId = ?")
        params.append(user["branchId"])
    sql = (
        "SELECT kr.id AS id, kr.date AS date, b.name AS branchName, "
        "COUNT(kri.id) AS itemCount "
        "FROM KitchenRequirement kr "
        "JOIN Branch b ON b.id = kr.branchId "
        "LEFT JOIN KitchenRequirementItem kri ON kri.requirementId = kr.id "
        f"WHERE {' AND '.join(conditions)} "
        "GROUP BY kr.id ORDER BY kr.date DESC, kr.createdAt DESC"
    )
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_rejected_requirements(conn: sqlite3.Connection, user: dict | None) -> list[dict]:
    """Requirements a reviewer sent back with a reason, not yet
    re-approved -- surfaced as a banner on the Kitchen Upload page so
    whoever has access there sees the reason and can fix the rows via the
    same review screen (rejected rows stay editable, same as any other
    not-yet-confirmed requirement)."""
    if user is None:
        return []
    conditions = ["kr.rejectedAt IS NOT NULL", "kr.confirmedAt IS NULL"]
    params: list = []
    if user.get("branchId"):
        conditions.append("kr.branchId = ?")
        params.append(user["branchId"])
    sql = (
        "SELECT kr.id AS id, kr.date AS date, kr.reviewComment AS comment, "
        "b.name AS branchName, u.name AS rejectedByName "
        "FROM KitchenRequirement kr "
        "JOIN Branch b ON b.id = kr.branchId "
        "LEFT JOIN User u ON u.id = kr.rejectedById "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY kr.rejectedAt DESC"
    )
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_confirmed_requirement_items(conn: sqlite3.Connection, branch_id: str, date_db: str) -> list[dict]:
    """Row-addressable (keyed by KitchenRequirementItem.id) confirmed rows
    for a branch/date, so the Requirements page can edit qty on the exact
    underlying row instead of an aggregated total -- see
    get_consolidated_requirement for the read-only aggregated view used
    elsewhere (e.g. the Daily Tracker's kitchenRequirement column).

    Carries requirementId/requirementCreatedAt so a caller can group rows
    by the upload ("batch") they came from -- if the kitchen team uploads
    a second sheet for the same date, its rows must stay visually
    separated from the first upload's, not interleaved into the same
    department card as if they were one entry (callers filter to a single
    requirementId themselves for a per-batch export)."""
    rows = conn.execute(
        "SELECT kri.id AS id, kri.qty AS qty, kri.unit AS unit, "
        "kr.id AS requirementId, kr.createdAt AS requirementCreatedAt, "
        "i.id AS itemId, i.name AS itemName, d.name AS departmentName "
        "FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId "
        "JOIN Item i ON i.id = kri.matchedItemId "
        "JOIN Department d ON d.id = kri.departmentId "
        "WHERE kr.branchId = ? AND kr.date = ? AND kr.confirmedAt IS NOT NULL AND kri.matchedItemId IS NOT NULL "
        "ORDER BY kr.createdAt ASC, d.name ASC, i.name ASC",
        (branch_id, date_db),
    ).fetchall()
    return [dict(r) for r in rows]


def update_confirmed_requirement_item_qty(conn: sqlite3.Connection, item_id: str, qty: float) -> None:
    """Unlike update_requirement_item (pre-confirm review edits), this is
    the post-confirm path: admin/manager adjusting the saved qty directly
    from the Requirements page. Only qty is editable here -- the item/
    department match is already locked in by confirmation."""
    row = conn.execute(
        "SELECT kri.id FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId "
        "WHERE kri.id = ? AND kr.confirmedAt IS NOT NULL",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Requirement item not found or not confirmed yet")
    conn.execute("UPDATE KitchenRequirementItem SET qty = ? WHERE id = ?", (qty, item_id))
    conn.commit()


def confirm_kitchen_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str,
                                 comment: str | None = None) -> None:
    req = conn.execute("SELECT * FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    items = conn.execute("SELECT * FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)).fetchall()

    unmatched = [i for i in items if not i["matchedItemId"]]
    if unmatched:
        raise ValueError(f"{len(unmatched)} row(s) still need an item selected before confirming")

    # Approving clears any earlier rejection -- a requirement can only be
    # in one state (pending / rejected / confirmed) at a time.
    conn.execute(
        "UPDATE KitchenRequirement SET confirmedById = ?, confirmedAt = ?, "
        "rejectedAt = NULL, rejectedById = NULL, reviewComment = ? WHERE id = ?",
        (user_id, now_db(), comment or None, requirement_id),
    )
    audit.write(conn, user_id, req["branchId"], "KITCHEN_REQUIREMENT_CONFIRMED",
                "KitchenRequirement", requirement_id, {"itemCount": len(items)})
    conn.commit()


def reject_kitchen_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str,
                                comment: str) -> None:
    """Sends a requirement back to Kitchen with a reason instead of
    confirming it. Rows stay exactly as they are (still editable, same as
    any other not-yet-confirmed requirement) -- there's no separate
    resubmit step, whoever fixes the rows (Kitchen or Admin/Manager) just
    confirms it afterward like normal."""
    if not comment or not comment.strip():
        raise ValueError("A comment is required when rejecting")
    req = conn.execute("SELECT id, confirmedAt FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")

    conn.execute(
        "UPDATE KitchenRequirement SET rejectedAt = ?, rejectedById = ?, reviewComment = ?, "
        "confirmedAt = NULL, confirmedById = NULL WHERE id = ?",
        (now_db(), user_id, comment.strip(), requirement_id),
    )
    conn.commit()
