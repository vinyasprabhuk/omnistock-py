"""Port of src/lib/actions/kitchenRequirement.ts."""
from __future__ import annotations

import sqlite3

from app.dates import date_key_to_db, from_db, now_db, today_key
from app.db import new_id
from app.services import audit, storage
from app.services.departments import find_or_create_department
from app.services.match_item import match_item, save_alias
from app.services.normalize_unit import normalize_unit
from app.services.transactions import create_stock_issue
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




def get_all_active_items(conn: sqlite3.Connection) -> list[dict]:
    """Every active Item Master row -- cold-start fallback for
    get_department_history_items, used when a department has no request
    history yet."""
    rows = conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC").fetchall()
    return [dict(r) for r in rows]


def get_department_history_items(conn: sqlite3.Connection, department_id: str) -> list[dict]:
    """Items historically requisitioned under this department, learned from
    past KitchenRequirementItem rows (originally populated by real Excel
    uploads, whose department blocks were each scoped to a real subset of
    items) rather than a curated Item<->Department mapping. Real data
    confirms this is genuinely many-to-many -- 12 of ~65 historically-
    matched items have appeared under 2-6 different departments -- so
    this is set-membership per department, not exclusive ownership.
    Empty result means a department with no history yet -- the caller
    falls back to every active Item Master row (get_all_active_items)."""
    rows = conn.execute(
        "SELECT DISTINCT i.id, i.name, i.unit FROM KitchenRequirementItem kri "
        "JOIN Item i ON i.id = kri.matchedItemId "
        "WHERE kri.departmentId = ? AND kri.matchedItemId IS NOT NULL AND i.active = 1 "
        "ORDER BY i.name ASC",
        (department_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_requestable_departments(conn: sqlite3.Connection) -> list[dict]:
    """Active departments for the Request Regular/Extra Items department
    picker -- excludes "Historical Import", a data-migration artifact
    department that was never a real place kitchen requests items for."""
    rows = conn.execute(
        "SELECT id, name FROM Department WHERE active = 1 AND name != 'Historical Import' ORDER BY name ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_draft_requirement_departments(conn: sqlite3.Connection, requirement_id: str) -> list[str]:
    """Distinct department names already saved into a still-Pending draft
    requirement, for the "Departments saved so far" summary while kitchen
    is still adding more."""
    rows = conn.execute(
        "SELECT DISTINCT d.name FROM KitchenRequirementItem kri "
        "JOIN Department d ON d.id = kri.departmentId WHERE kri.requirementId = ? ORDER BY d.name",
        (requirement_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def save_department_to_requirement(conn: sqlite3.Connection, user_id: str, branch_id: str,
                                    requirement_id: str | None, department_id: str, date_key: str,
                                    request_type: str, lines: list[dict]) -> str:
    """The "Save" action for one department on the Request Regular/Extra
    Items entry screen -- no OCR/text-matching involved, every line
    already carries a real Item Master id, so each row is created at
    AUTO/100 confidence. Treated as one ongoing transaction per
    Regular/Extra session: the first department's Save creates a new
    PENDING KitchenRequirement (requirement_id=None); every subsequent
    department's Save (requirement_id passed back from the first) appends
    its items into that SAME requirement, so a multi-department request
    still ends up as one requirement, one transaction, matching how the
    old Excel upload always produced a single multi-department
    requirement. Blank/zero quantities are the caller's job to filter out
    before calling this (lines here are assumed already qty > 0).

    lines: [{"itemId": str, "qty": float}, ...]
    Returns the requirement_id (new or the same one passed in).
    """
    if request_type not in ("REGULAR", "EXTRA"):
        raise ValueError("Invalid request type")
    if not lines:
        raise ValueError("Add at least one item")

    if requirement_id:
        req = conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
        if req is None:
            raise ValueError("Requirement not found")
        if req["status"] != "PENDING":
            raise ValueError("This request is no longer open for adding departments")
    else:
        requirement_id = new_id()
        conn.execute(
            "INSERT INTO KitchenRequirement (id, uploadId, branchId, date, createdAt, status, requestType) "
            "VALUES (?, NULL, ?, ?, ?, 'PENDING', ?)",
            (requirement_id, branch_id, date_key_to_db(date_key), now_db(), request_type),
        )

    for line in lines:
        item = conn.execute("SELECT name, unit FROM Item WHERE id = ?", (line["itemId"],)).fetchone()
        if item is None:
            continue
        conn.execute(
            "INSERT INTO KitchenRequirementItem (id, requirementId, departmentId, extractedText, "
            "matchedItemId, qty, unit, confidence, status, createdAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 100, 'AUTO', ?)",
            (new_id(), requirement_id, department_id, item["name"], line["itemId"],
             line["qty"], item["unit"], now_db()),
        )
    conn.commit()
    return requirement_id


def get_open_requirements_for_kitchen(conn: sqlite3.Connection, branch_id: str, request_type: str,
                                       date_db: str | None = None) -> list[dict]:
    """Backs the Pending/Approved list on the Kitchen Upload page -- Kitchen
    has no access to /requirements (admin/manager/viewer only), so this is
    the only place they can see their team's outstanding requests, both
    while still Pending and after an admin has Approved it (Approved is
    included so Kitchen can reach the review page's lock icon / "Request
    an edit" control -- once Issued a requirement drops out of this list
    since nothing further can be done with it). Scoped to the branch (not
    just the current user) since kitchen staff share the same queue, and
    to one requestType at a time (Regular and Extra are shown as two
    separate lists, each its own transaction). Scoped to a specific date
    when date_db is given -- the Kitchen Upload page's date picker filters
    this list to that date, since a request can be for any date (including
    future ones), not just today."""
    conditions = ["kr.branchId = ?", "kr.requestType = ?", "kr.status IN ('PENDING', 'APPROVED')"]
    params: list = [branch_id, request_type]
    if date_db:
        conditions.append("kr.date = ?")
        params.append(date_db)
    rows = conn.execute(
        "SELECT kr.id AS id, kr.date AS date, kr.createdAt AS createdAt, kr.status AS status, "
        "cu.name AS confirmedByName, "
        "COUNT(kri.id) AS itemCount, "
        "GROUP_CONCAT(DISTINCT d.name) AS departmentNames "
        "FROM KitchenRequirement kr "
        "LEFT JOIN KitchenRequirementItem kri ON kri.requirementId = kr.id "
        "LEFT JOIN Department d ON d.id = kri.departmentId "
        "LEFT JOIN User cu ON cu.id = kr.confirmedById "
        f"WHERE {' AND '.join(conditions)} "
        "GROUP BY kr.id ORDER BY kr.createdAt DESC",
        params,
    ).fetchall()
    results = [dict(r) for r in rows]
    for r in results:
        r["dateKey"] = from_db(r["date"]).strftime("%Y-%m-%d")
    return results


def get_requirement_for_review(conn: sqlite3.Connection, requirement_id: str) -> dict:
    req = conn.execute(
        "SELECT kr.*, cu.name AS confirmedByName, iu.name AS issuedByName "
        "FROM KitchenRequirement kr "
        "LEFT JOIN User cu ON cu.id = kr.confirmedById "
        "LEFT JOIN User iu ON iu.id = kr.issuedById "
        "WHERE kr.id = ?", (requirement_id,),
    ).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    items = conn.execute(
        "SELECT kri.*, d.name AS departmentName, i.name AS matchedItemName "
        "FROM KitchenRequirementItem kri "
        "JOIN Department d ON d.id = kri.departmentId "
        "LEFT JOIN Item i ON i.id = kri.matchedItemId "
        "WHERE kri.requirementId = ? ORDER BY d.name ASC, kri.createdAt ASC",
        (requirement_id,),
    ).fetchall()
    upload = None
    if req["uploadId"]:
        upload = conn.execute("SELECT * FROM Upload WHERE id = ?", (req["uploadId"],)).fetchone()
    return {"requirement": dict(req), "items": [dict(r) for r in items], "upload": dict(upload) if upload else None}


def update_requirement_item(conn: sqlite3.Connection, item_id: str, department_name: str | None,
                             matched_item_id: str | None, qty: float | None, unit: str | None) -> None:
    item = conn.execute(
        "SELECT kri.*, kr.status AS requirementStatus FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId WHERE kri.id = ?", (item_id,)
    ).fetchone()
    if item is None:
        raise ValueError("Item not found")
    if item["requirementStatus"] != "PENDING":
        raise ValueError("Cannot edit a requirement that isn't pending")

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
    req = conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["status"] != "PENDING":
        raise ValueError("Cannot edit a requirement that isn't pending")

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
        "SELECT kri.requirementId, kr.status FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId WHERE kri.id = ?", (item_id,)
    ).fetchone()
    if item is None:
        raise ValueError("Item not found")
    if item["status"] != "PENDING":
        raise ValueError("Cannot edit a requirement that isn't pending")
    conn.execute("DELETE FROM KitchenRequirementItem WHERE id = ?", (item_id,))
    conn.commit()


def get_pending_requirements_for_branch_date(conn: sqlite3.Connection, branch_id: str, date_db: str) -> list[dict]:
    """Requirements awaiting admin/manager approval for a specific branch/
    date -- backs the Requirements page's Pending section, where
    Approve/Reject live (row editing -- matched item, qty, department --
    still happens on the Kitchen review screen, linked from here)."""
    rows = conn.execute(
        "SELECT kr.id AS id, kr.createdAt AS createdAt, kr.requestType AS requestType, "
        "COUNT(kri.id) AS itemCount, "
        "SUM(CASE WHEN kri.matchedItemId IS NULL THEN 1 ELSE 0 END) AS unmatchedCount "
        "FROM KitchenRequirement kr "
        "LEFT JOIN KitchenRequirementItem kri ON kri.requirementId = kr.id "
        "WHERE kr.branchId = ? AND kr.date = ? AND kr.status = 'PENDING' "
        "GROUP BY kr.id ORDER BY kr.createdAt ASC",
        (branch_id, date_db),
    ).fetchall()
    return [dict(r) for r in rows]


def get_pending_requirements(conn: sqlite3.Connection, user: dict) -> list[dict]:
    """Requirements awaiting admin/manager approval, scoped to the user's
    branch (or every branch for a not-branch-locked admin). Backs both the
    Kitchen Upload page's 'Pending Review' list and the nav badge count."""
    return _requirements_by_status(conn, user, "PENDING")


def get_approved_requirements_for_branch_date(conn: sqlite3.Connection, branch_id: str, date_db: str) -> list[dict]:
    """Requirements approved but not yet issued, for a specific branch/
    date -- backs the Requirements page's Approved section, where the
    Issue action lives."""
    rows = conn.execute(
        "SELECT kr.id AS id, kr.createdAt AS createdAt, kr.requestType AS requestType, "
        "kr.confirmedById AS confirmedById, kr.confirmedAt AS confirmedAt, "
        "COUNT(kri.id) AS itemCount "
        "FROM KitchenRequirement kr "
        "LEFT JOIN KitchenRequirementItem kri ON kri.requirementId = kr.id "
        "WHERE kr.branchId = ? AND kr.date = ? AND kr.status = 'APPROVED' "
        "GROUP BY kr.id ORDER BY kr.createdAt ASC",
        (branch_id, date_db),
    ).fetchall()
    return [dict(r) for r in rows]


def get_approved_requirements(conn: sqlite3.Connection, user: dict) -> list[dict]:
    """Approved-but-not-yet-issued requirements, scoped like
    get_pending_requirements. Backs the second nav badge."""
    return _requirements_by_status(conn, user, "APPROVED")


def _requirements_by_status(conn: sqlite3.Connection, user: dict, status: str) -> list[dict]:
    if user is None or user["role"] not in ("ADMIN", "MANAGER"):
        return []
    conditions = ["kr.status = ?"]
    params: list = [status]
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


def get_action_dates_for_branch(conn: sqlite3.Connection, branch_id: str) -> list[dict]:
    """Distinct dates (across every PENDING/APPROVED requirement) needing
    admin action for a branch, each with its own pending/approved counts.
    The Requirements page is scoped to a single selected date, but a
    kitchen request can be dated for the past or a future date (not just
    today), so an admin sitting on "today" with nothing to review here has
    no other way to discover that action is actually needed on a
    different date -- this backs a banner pointing them at it."""
    rows = conn.execute(
        "SELECT kr.date AS date, kr.status AS status, COUNT(*) AS requirementCount "
        "FROM KitchenRequirement kr "
        "WHERE kr.branchId = ? AND kr.status IN ('PENDING', 'APPROVED') "
        "GROUP BY kr.date, kr.status",
        (branch_id,),
    ).fetchall()
    by_date: dict[str, dict] = {}
    for r in rows:
        entry = by_date.setdefault(r["date"], {"date": r["date"], "pendingCount": 0, "approvedCount": 0})
        if r["status"] == "PENDING":
            entry["pendingCount"] = r["requirementCount"]
        else:
            entry["approvedCount"] = r["requirementCount"]
    results = sorted(by_date.values(), key=lambda r: r["date"])
    for r in results:
        r["dateKey"] = from_db(r["date"]).strftime("%Y-%m-%d")
    return results


def get_requirement_items_by_status(conn: sqlite3.Connection, branch_id: str, date_db: str, status: str) -> list[dict]:
    """Row-addressable (keyed by KitchenRequirementItem.id) rows for a
    branch/date at a given KitchenRequirement.status, so the Requirements
    page can edit qty on the exact underlying row instead of an aggregated
    total -- see get_consolidated_requirement for the read-only aggregated
    view used elsewhere (e.g. the Daily Tracker's kitchenRequirement
    column). Used for both the Approved section (editable, lock-icon
    eligible) and the Issued section (read-only), by status.

    Carries requirementId/requirementCreatedAt/requestType so a caller can
    group rows by the requirement ("batch") they came from -- if the
    kitchen team submits a second request for the same date, its rows
    must stay visually separated from the first's, not interleaved into
    the same department card as if they were one entry."""
    rows = conn.execute(
        "SELECT kri.id AS id, kri.qty AS qty, kri.unit AS unit, "
        "kr.id AS requirementId, kr.createdAt AS requirementCreatedAt, kr.requestType AS requestType, "
        "kr.confirmedById AS confirmedById, cu.name AS confirmedByName, kr.confirmedAt AS confirmedAt, "
        "kr.issuedById AS issuedById, iu.name AS issuedByName, kr.issuedAt AS issuedAt, "
        "i.id AS itemId, i.name AS itemName, d.name AS departmentName "
        "FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId "
        "JOIN Item i ON i.id = kri.matchedItemId "
        "JOIN Department d ON d.id = kri.departmentId "
        "LEFT JOIN User cu ON cu.id = kr.confirmedById "
        "LEFT JOIN User iu ON iu.id = kr.issuedById "
        "WHERE kr.branchId = ? AND kr.date = ? AND kr.status = ? AND kri.matchedItemId IS NOT NULL "
        "ORDER BY kr.createdAt ASC, d.name ASC, i.name ASC",
        (branch_id, date_db, status),
    ).fetchall()
    return [dict(r) for r in rows]


def edit_approved_requirement_qty(conn: sqlite3.Connection, item_id: str, qty: float) -> None:
    """Admin/manager adjusting a saved qty directly from the Requirements
    page while the requirement is Approved but not yet Issued (the "store
    only has 2kg not 4kg" case) -- reason-free, unlike the Kitchen-side
    request_requirement_edit/submit_requirement_edit flow below. Only qty
    is editable here -- item/department match is already locked in.

    Scoped to status == 'APPROVED' specifically (excludes ISSUED): this is
    what makes the old latent bug (qty edits silently not reflected in an
    already-created StockIssueItem, since issuing used to happen at
    confirm-time) structurally impossible -- no StockIssueItem exists yet
    while APPROVED, and this refuses to run once ISSUED.

    qty <= 0 removes the row outright rather than leaving a zero-qty line
    -- same convention as the Kitchen-side edit flow's DELETE branch, so
    zeroing an item here never produces a zero-qty StockIssueItem at
    Issue time."""
    row = conn.execute(
        "SELECT kri.id FROM KitchenRequirementItem kri "
        "JOIN KitchenRequirement kr ON kr.id = kri.requirementId "
        "WHERE kri.id = ? AND kr.status = 'APPROVED'",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Requirement item not found or not approved yet")
    if qty <= 0:
        conn.execute("DELETE FROM KitchenRequirementItem WHERE id = ?", (item_id,))
    else:
        conn.execute("UPDATE KitchenRequirementItem SET qty = ? WHERE id = ?", (qty, item_id))
    conn.commit()


def auto_issue_stock_from_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str) -> list[str]:
    """Called by issue_kitchen_requirement once an admin has manually
    confirmed stock was physically handed over. Daily Tracker's "issued"
    figures are a live sum over StockIssueItem, so they reflect this the
    moment it runs, with no separate update needed. One StockIssue per
    department, same as a manual issue (Stock Issue is always scoped to a
    single department per entry), each linked back to this requirement via
    sourceRequirementId."""
    req = conn.execute("SELECT * FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    rows = conn.execute(
        "SELECT kri.matchedItemId AS itemId, kri.qty AS qty, d.name AS departmentName "
        "FROM KitchenRequirementItem kri JOIN Department d ON d.id = kri.departmentId "
        "WHERE kri.requirementId = ? AND kri.matchedItemId IS NOT NULL",
        (requirement_id,),
    ).fetchall()
    if not rows:
        return []

    date_key = from_db(req["date"]).strftime("%Y-%m-%d")
    by_dept: dict[str, list[dict]] = {}
    for r in rows:
        by_dept.setdefault(r["departmentName"], []).append({"itemId": r["itemId"], "qty": r["qty"]})

    return [
        create_stock_issue(conn, user_id, req["branchId"], date_key, dept_name, lines,
                            source_requirement_id=requirement_id)
        for dept_name, lines in by_dept.items()
    ]


def approve_kitchen_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str,
                                 comment: str | None = None) -> None:
    """Approve does NOT issue stock -- that's the separate, later
    issue_kitchen_requirement step, triggered only once an admin has
    manually confirmed with kitchen/store that items were physically
    handed over. This lets an admin approve, then adjust quantities
    against real stock-room reality (edit_approved_requirement_qty)
    before anything actually moves in Daily Tracker."""
    req = conn.execute("SELECT * FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["status"] != "PENDING":
        raise ValueError("Requirement is not pending approval")
    items = conn.execute("SELECT * FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)).fetchall()

    unmatched = [i for i in items if not i["matchedItemId"]]
    if unmatched:
        raise ValueError(f"{len(unmatched)} row(s) still need an item selected before approving")

    conn.execute(
        "UPDATE KitchenRequirement SET confirmedById = ?, confirmedAt = ?, reviewComment = ?, status = 'APPROVED' "
        "WHERE id = ?",
        (user_id, now_db(), comment or None, requirement_id),
    )
    audit.write(conn, user_id, req["branchId"], "KITCHEN_REQUIREMENT_CONFIRMED",
                "KitchenRequirement", requirement_id, {"itemCount": len(items)})
    conn.commit()


def issue_kitchen_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str) -> list[str]:
    """The manual "Issued" action -- an admin clicks this only after
    getting real-world confirmation that stock was physically handed
    over. This is what actually creates StockIssue/StockIssueItem rows
    (via auto_issue_stock_from_requirement), so Daily Tracker only moves
    at this point, never at mere Approval."""
    req = conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["status"] != "APPROVED":
        raise ValueError("Requirement must be approved before it can be issued")

    issue_ids = auto_issue_stock_from_requirement(conn, user_id, requirement_id)
    conn.execute(
        "UPDATE KitchenRequirement SET status = 'ISSUED', issuedById = ?, issuedAt = ? WHERE id = ?",
        (user_id, now_db(), requirement_id),
    )
    conn.commit()
    return issue_ids


def request_requirement_edit(conn: sqlite3.Connection, user_id: str, requirement_id: str, reason: str) -> str:
    """Kitchen's "unlock editing" checkpoint on an Approved requirement --
    requires a mandatory top-level reason (mirrors reject_kitchen_requirement's
    existing required-comment style exactly). Does not itself change
    status -- an abandoned edit request (reason given, no changes made)
    leaves the requirement untouched; only submit_requirement_edit reverts
    it to Pending."""
    if not reason or not reason.strip():
        raise ValueError("A reason is required to edit an approved requirement")
    req = conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["status"] != "APPROVED":
        raise ValueError("Only an approved (not yet issued) requirement can be edited this way")

    edit_id = new_id()
    conn.execute(
        "INSERT INTO KitchenRequirementEdit (id, requirementId, editedById, reason, createdAt) "
        "VALUES (?, ?, ?, ?, ?)",
        (edit_id, requirement_id, user_id, reason.strip(), now_db()),
    )
    conn.commit()
    return edit_id


def submit_requirement_edit(conn: sqlite3.Connection, user_id: str, requirement_id: str,
                             edit_id: str, lines: list[dict]) -> None:
    """Applies the actual item changes for an unlocked edit session.
    lines: [{"itemId": str, "qty": float, "reason": str | None}] -- qty=0
    means "remove this item". Every line whose qty differs from what's
    currently committed (or that's new) requires a non-blank reason,
    named to the specific item so the UI can surface it inline. Reverts
    the requirement to Pending on success, requiring a fresh admin
    approval (and later re-Issue) before it can affect stock again."""
    req = conn.execute("SELECT status, branchId FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["status"] != "APPROVED":
        raise ValueError("This requirement is no longer open for edits")
    edit = conn.execute(
        "SELECT id FROM KitchenRequirementEdit WHERE id = ? AND requirementId = ?", (edit_id, requirement_id)
    ).fetchone()
    if edit is None:
        raise ValueError("Edit session not found -- request an edit again")

    existing_rows = conn.execute(
        "SELECT id, matchedItemId, qty, departmentId FROM KitchenRequirementItem "
        "WHERE requirementId = ? AND matchedItemId IS NOT NULL", (requirement_id,)
    ).fetchall()
    existing_by_item = {r["matchedItemId"]: r for r in existing_rows}
    # Requirements from the new entry flow are single-department; grab it
    # once up front so a brand-new item added mid-session (see ADD below)
    # doesn't depend on some other row still existing at insert time.
    department_id = existing_rows[0]["departmentId"] if existing_rows else None

    changes = []
    for line in lines:
        item_id = line["itemId"]
        new_qty = float(line["qty"])
        existing = existing_by_item.get(item_id)
        previous_qty = existing["qty"] if existing else None
        if existing is not None and abs(previous_qty - new_qty) < 1e-9:
            continue  # unchanged -- no row, no reason required

        reason = (line.get("reason") or "").strip()
        item_row = conn.execute("SELECT name, unit FROM Item WHERE id = ?", (item_id,)).fetchone()
        item_name = item_row["name"] if item_row else item_id
        if not reason:
            raise ValueError(f"Enter a reason for changing {item_name}")

        if existing is None:
            if department_id is None:
                raise ValueError(f"Can't determine a department for {item_name} -- add at least one existing item first")
            requirement_item_id = new_id()
            conn.execute(
                "INSERT INTO KitchenRequirementItem (id, requirementId, departmentId, extractedText, "
                "matchedItemId, qty, unit, confidence, status, createdAt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 100, 'AUTO', ?)",
                (requirement_item_id, requirement_id, department_id, item_row["name"], item_id,
                 new_qty, item_row["unit"], now_db()),
            )
            action, previous_qty = "ADD", None
        elif new_qty <= 0:
            conn.execute("DELETE FROM KitchenRequirementItem WHERE id = ?", (existing["id"],))
            action, requirement_item_id = "DELETE", None  # row is gone -- nothing left to reference
        else:
            requirement_item_id = existing["id"]
            conn.execute("UPDATE KitchenRequirementItem SET qty = ? WHERE id = ?", (new_qty, requirement_item_id))
            action = "UPDATE"

        changes.append((requirement_item_id, item_name, action, previous_qty,
                         None if action == "DELETE" else new_qty, reason))

    for requirement_item_id, item_name, action, previous_qty, new_qty, reason in changes:
        conn.execute(
            "INSERT INTO KitchenRequirementItemChange (id, editId, requirementItemId, itemLabel, action, "
            "previousQty, newQty, reason, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), edit_id, requirement_item_id, item_name, action, previous_qty, new_qty, reason, now_db()),
        )

    conn.execute("UPDATE KitchenRequirement SET status = 'PENDING' WHERE id = ?", (requirement_id,))
    conn.commit()


def reject_kitchen_requirement(conn: sqlite3.Connection, user_id: str, requirement_id: str,
                                comment: str) -> None:
    """Rejecting deletes the requirement outright (confirmed with user) --
    Kitchen uploads a fresh sheet rather than fixing rows in place. Also
    removes the Upload record (not the stored file itself, since storage
    is content-addressed by hash and another Upload row could share the
    same bytes) so a resubmitted file with identical content doesn't
    incorrectly trip the duplicate-upload check against a requirement
    that no longer exists."""
    if not comment or not comment.strip():
        raise ValueError("A comment is required when rejecting")
    req = conn.execute("SELECT id, uploadId, status FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
    if req is None:
        raise ValueError("Requirement not found")
    if req["status"] != "PENDING":
        raise ValueError("Already approved -- nothing to reject")

    conn.execute("DELETE FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,))
    conn.execute("DELETE FROM KitchenRequirement WHERE id = ?", (requirement_id,))
    if req["uploadId"]:
        conn.execute("DELETE FROM Upload WHERE id = ?", (req["uploadId"],))
    conn.commit()
