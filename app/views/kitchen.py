from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin
from app.auth.session import ForbiddenError, resolve_branch_scope
from app.dates import date_key_to_db, from_db, today_key
from app.security import require_write
from app.services.kitchen_requirement import (
    add_manual_requirement_item,
    approve_kitchen_requirement,
    delete_requirement_item,
    get_all_active_items,
    get_department_history_items,
    get_draft_requirement_departments,
    get_open_requirements_for_kitchen,
    get_requestable_departments,
    get_requirement_for_review,
    issue_kitchen_requirement,
    reject_kitchen_requirement,
    request_requirement_edit,
    save_department_to_requirement,
    submit_requirement_edit,
    update_requirement_item,
    upload_kitchen_screenshot,
)

bp = Blueprint("kitchen", __name__)

STRUCTURED_EXTENSIONS = (".xlsx", ".xls", ".docx", ".doc")


@bp.route("/kitchen", methods=["GET"])
def index():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    branches = list_branches_for_admin(conn) if not user_branch_id else []
    date = request.args.get("date") or today_key()
    pending_regular = pending_extra = []
    branch_for_pending = user_branch_id or request.args.get("branchId")
    if branch_for_pending:
        date_db = date_key_to_db(date)
        pending_regular = get_open_requirements_for_kitchen(conn, branch_for_pending, "REGULAR", date_db)
        pending_extra = get_open_requirements_for_kitchen(conn, branch_for_pending, "EXTRA", date_db)
    return render_template(
        "kitchen/index.html", branches=branches, user_branch_id=user_branch_id, today=today_key(),
        pending_regular=pending_regular, pending_extra=pending_extra, branch_id=branch_for_pending or "",
        date=date,
    )


@bp.route("/kitchen/request", methods=["GET"])
def request_entry():
    conn = g.conn
    request_type = (request.args.get("type") or "regular").upper()
    if request_type not in ("REGULAR", "EXTRA"):
        request_type = "REGULAR"
    department_id = request.args.get("departmentId") or ""
    requirement_id = request.args.get("requirementId") or ""
    user_branch_id = g.user.get("branchId")
    branches = list_branches_for_admin(conn) if not user_branch_id else []
    branch_id = user_branch_id or request.args.get("branchId") or ""
    if not branch_id and branches:
        # The <select> shows the first branch selected by default even
        # before the user touches it -- match that visually-implied choice
        # in the URLs we build too, so the very first click through
        # (department, then Save) doesn't fail with "Select a branch
        # first." just because the dropdown was never explicitly changed.
        branch_id = branches[0]["id"]
    date = request.args.get("date") or today_key()

    saved_departments: list[str] = []
    if requirement_id:
        req = conn.execute("SELECT status, date, branchId FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
        if req is None or req["status"] != "PENDING":
            flash("That request is no longer open for adding departments.", "error")
            requirement_id = ""
        else:
            saved_departments = get_draft_requirement_departments(conn, requirement_id)
            date = from_db(req["date"]).strftime("%Y-%m-%d")
            branch_id = req["branchId"]

    if not department_id:
        departments = get_requestable_departments(conn)
        return render_template(
            "kitchen/request.html", step="department", request_type=request_type,
            departments=departments, branches=branches, branch_id=branch_id,
            user_branch_id=user_branch_id, date=date, requirement_id=requirement_id,
            saved_departments=saved_departments,
        )

    department = conn.execute("SELECT id, name FROM Department WHERE id = ?", (department_id,)).fetchone()
    if department is None:
        flash("Department not found.", "error")
        return redirect(url_for("kitchen.request_entry", type=request_type.lower(), requirementId=requirement_id))

    items = get_department_history_items(conn, department_id)
    used_fallback = False
    if not items:
        items = get_all_active_items(conn)
        used_fallback = True

    return render_template(
        "kitchen/request.html", step="items", request_type=request_type, department=department,
        items=items, used_fallback=used_fallback, branch_id=branch_id, date=date, requirement_id=requirement_id,
    )


@bp.route("/kitchen/request/save", methods=["POST"])
@require_write
def request_save():
    conn = g.conn
    request_type = (request.form.get("requestType") or "REGULAR").upper()
    department_id = request.form.get("departmentId") or ""
    requirement_id = request.form.get("requirementId") or None
    user_branch_id = g.user.get("branchId")
    branch_id = user_branch_id or request.form.get("branchId")
    date_key = request.form.get("date") or today_key()

    if not branch_id:
        flash("Select a branch first.", "error")
        return redirect(url_for("kitchen.request_entry", type=request_type.lower(), requirementId=requirement_id))
    if not department_id:
        flash("Select a department first.", "error")
        return redirect(url_for("kitchen.request_entry", type=request_type.lower(), requirementId=requirement_id))

    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")
    lines = []
    for item_id, qty in zip(item_ids, qtys):
        if not item_id or not qty:
            continue
        try:
            qty_val = float(qty)
        except ValueError:
            continue
        if qty_val > 0:
            lines.append({"itemId": item_id, "qty": qty_val})

    try:
        requirement_id = save_department_to_requirement(
            conn, g.user["id"], branch_id, requirement_id, department_id, date_key, request_type, lines,
        )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("kitchen.request_entry", type=request_type.lower(),
                                 departmentId=department_id, requirementId=requirement_id))
    flash("Department saved. Add another department, or Submit to finish.", "success")
    return redirect(url_for("kitchen.request_entry", type=request_type.lower(), requirementId=requirement_id))


@bp.route("/kitchen/upload", methods=["POST"])
@require_write
def upload():
    conn = g.conn
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a file first.", "error")
        return redirect(url_for("kitchen.index"))

    user_branch_id = g.user.get("branchId")
    branch_id = user_branch_id or request.form.get("branchId")
    if not branch_id:
        flash("Select a branch first.", "error")
        return redirect(url_for("kitchen.index"))

    date_key = request.form.get("date") or None
    force = request.form.get("force") == "true"

    result = upload_kitchen_screenshot(
        conn, g.user["id"], branch_id, file.read(), file.filename, file.mimetype, date_key, force,
    )

    if result.get("duplicate"):
        return render_template(
            "kitchen/duplicate.html", duplicate=result["duplicate"],
            date=date_key or today_key(), branch_id=branch_id, filename=file.filename,
        )

    if result.get("manualEntry"):
        flash("This file type isn't read automatically. Enter the requirement manually below.", "message")

    return redirect(url_for("kitchen.review", requirement_id=result["requirementId"]))


@bp.route("/kitchen/review/<requirement_id>", methods=["GET"])
def review(requirement_id: str):
    conn = g.conn
    data = get_requirement_for_review(conn, requirement_id)
    req = data["requirement"]
    try:
        resolve_branch_scope(g.user, req["branchId"])
    except ForbiddenError:
        flash("You don't have access to that requirement.", "error")
        return redirect(url_for("kitchen.index"))

    items = [dict(r) for r in conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC")]
    departments = [r["name"] for r in conn.execute("SELECT name FROM Department WHERE active = 1 ORDER BY name ASC")]

    upload_ext = ""
    if data["upload"] and "." in data["upload"]["filePath"]:
        upload_ext = "." + data["upload"]["filePath"].rsplit(".", 1)[-1].lower()
    was_structured_file = upload_ext in STRUCTURED_EXTENSIONS

    unmatched_count = sum(1 for i in data["items"] if not i["matchedItemId"])
    can_request_edit = req["status"] == "APPROVED" and g.user["role"] == "KITCHEN"

    return render_template(
        "kitchen/review.html", requirement=req, items=data["items"], all_items=items,
        departments=departments, was_structured_file=was_structured_file,
        unmatched_count=unmatched_count, date_key=from_db(req["date"]).strftime("%Y-%m-%d"),
        can_request_edit=can_request_edit,
    )


@bp.route("/kitchen/review/<requirement_id>/item/<item_id>/update", methods=["POST"])
@require_write
def update_item(requirement_id: str, item_id: str):
    conn = g.conn
    matched_item_id = request.form.get("matchedItemId") or None
    qty = request.form.get("qty")
    unit = request.form.get("unit") or None
    department_name = request.form.get("departmentName") or None
    try:
        update_requirement_item(
            conn, item_id, department_name, matched_item_id,
            float(qty) if qty else None, unit,
        )
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("kitchen.review", requirement_id=requirement_id))


@bp.route("/kitchen/review/<requirement_id>/item/add", methods=["POST"])
@require_write
def add_item(requirement_id: str):
    conn = g.conn
    department_name = request.form.get("departmentName") or ""
    item_text = request.form.get("itemText") or ""
    matched_item_id = request.form.get("matchedItemId") or None
    qty = request.form.get("qty") or "0"
    unit = request.form.get("unit") or ""
    try:
        add_manual_requirement_item(conn, requirement_id, department_name, item_text, matched_item_id, float(qty), unit)
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("kitchen.review", requirement_id=requirement_id))


@bp.route("/kitchen/review/<requirement_id>/item/<item_id>/delete", methods=["POST"])
@require_write
def delete_item(requirement_id: str, item_id: str):
    conn = g.conn
    try:
        delete_requirement_item(conn, item_id)
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("kitchen.review", requirement_id=requirement_id))


@bp.route("/kitchen/review/<requirement_id>/confirm", methods=["POST"])
@require_write
def confirm(requirement_id: str):
    # Approve/Reject/Issue live on the Requirements page now, not here --
    # this route just carries out the action and bounces back to wherever
    # the form was submitted from (Requirements, by date/branch).
    if g.user["role"] not in ("ADMIN", "MANAGER"):
        abort(403, description="Only Admin/Manager can approve a requirement")
    conn = g.conn
    comment = request.form.get("comment") or None
    date = request.form.get("date") or today_key()
    branch_id = request.form.get("branchId") or ""
    try:
        approve_kitchen_requirement(conn, g.user["id"], requirement_id, comment)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("requirements.index", date=date, branchId=branch_id))
    flash("Requirement approved. Click Issue once stock has actually been handed over.", "success")
    return redirect(url_for("requirements.index", date=date, branchId=branch_id))


@bp.route("/kitchen/review/<requirement_id>/reject", methods=["POST"])
@require_write
def reject(requirement_id: str):
    if g.user["role"] not in ("ADMIN", "MANAGER"):
        abort(403, description="Only Admin/Manager can reject a requirement")
    conn = g.conn
    comment = request.form.get("comment") or ""
    date = request.form.get("date") or today_key()
    branch_id = request.form.get("branchId") or ""
    try:
        reject_kitchen_requirement(conn, g.user["id"], requirement_id, comment)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("requirements.index", date=date, branchId=branch_id))
    flash("Requirement rejected and removed.", "success")
    return redirect(url_for("requirements.index", date=date, branchId=branch_id))


@bp.route("/kitchen/review/<requirement_id>/issue", methods=["POST"])
@require_write
def issue(requirement_id: str):
    if g.user["role"] not in ("ADMIN", "MANAGER"):
        abort(403, description="Only Admin/Manager can issue a requirement to stock")
    conn = g.conn
    date = request.form.get("date") or today_key()
    branch_id = request.form.get("branchId") or ""
    try:
        issue_kitchen_requirement(conn, g.user["id"], requirement_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("requirements.index", date=date, branchId=branch_id))
    flash("Requirement issued to stock.", "success")
    return redirect(url_for("requirements.index", date=date, branchId=branch_id))


@bp.route("/kitchen/review/<requirement_id>/request-edit", methods=["POST"])
@require_write
def request_edit(requirement_id: str):
    if g.user["role"] != "KITCHEN":
        abort(403, description="Only Kitchen can request an edit to an approved requirement")
    conn = g.conn
    reason = request.form.get("reason") or ""
    try:
        edit_id = request_requirement_edit(conn, g.user["id"], requirement_id, reason)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("kitchen.review", requirement_id=requirement_id))
    return redirect(url_for("kitchen.edit_entry", requirement_id=requirement_id, editId=edit_id))


@bp.route("/kitchen/review/<requirement_id>/edit", methods=["GET"])
def edit_entry(requirement_id: str):
    conn = g.conn
    edit_id = request.args.get("editId") or ""
    data = get_requirement_for_review(conn, requirement_id)
    req = data["requirement"]
    try:
        resolve_branch_scope(g.user, req["branchId"])
    except ForbiddenError:
        flash("You don't have access to that requirement.", "error")
        return redirect(url_for("kitchen.index"))
    if req["status"] != "APPROVED" or not edit_id:
        flash("This requirement isn't open for edits right now.", "error")
        return redirect(url_for("kitchen.review", requirement_id=requirement_id))

    return render_template(
        "kitchen/request.html", step="edit", request_type=req["requestType"], edit_id=edit_id,
        requirement=req, items=data["items"], date=from_db(req["date"]).strftime("%Y-%m-%d"),
    )


@bp.route("/kitchen/review/<requirement_id>/edit/submit", methods=["POST"])
@require_write
def edit_submit(requirement_id: str):
    conn = g.conn
    edit_id = request.form.get("editId") or ""
    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")
    reasons = request.form.getlist("reason")

    lines = []
    for item_id, qty, reason in zip(item_ids, qtys, reasons):
        if not item_id or qty == "":
            continue
        try:
            qty_val = float(qty)
        except ValueError:
            continue
        lines.append({"itemId": item_id, "qty": qty_val, "reason": reason})

    try:
        submit_requirement_edit(conn, g.user["id"], requirement_id, edit_id, lines)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("kitchen.edit_entry", requirement_id=requirement_id, editId=edit_id))
    flash("Changes submitted -- this requirement is pending admin approval again.", "success")
    return redirect(url_for("kitchen.review", requirement_id=requirement_id))
