from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin
from app.auth.session import ForbiddenError, resolve_branch_scope
from app.dates import today_key
from app.security import require_write
from app.services.kitchen_requirement import (
    add_manual_requirement_item,
    confirm_kitchen_requirement,
    create_manual_requirement,
    delete_requirement_item,
    get_requirement_for_review,
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
    items = [dict(r) for r in conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC")]
    departments = [r["name"] for r in conn.execute("SELECT name FROM Department WHERE active = 1 ORDER BY name ASC")]
    return render_template(
        "kitchen/index.html", branches=branches, user_branch_id=user_branch_id, today=today_key(),
        items=items, departments=departments,
    )


@bp.route("/kitchen/manual-entry", methods=["POST"])
@require_write
def manual_entry():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    branch_id = user_branch_id or request.form.get("branchId")
    date_key = request.form.get("date") or today_key()

    if not branch_id:
        flash("Select a branch first.", "error")
        return redirect(url_for("kitchen.index"))

    department_names = request.form.getlist("departmentName")
    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")

    lines = []
    for dept, item_id, qty in zip(department_names, item_ids, qtys):
        if item_id and qty:
            try:
                lines.append({"departmentName": dept, "itemId": item_id, "qty": float(qty)})
            except ValueError:
                continue

    if not lines:
        flash("Add at least one item with a quantity.", "error")
        return redirect(url_for("kitchen.index"))

    requirement_id = create_manual_requirement(conn, g.user["id"], branch_id, date_key, lines)
    return redirect(url_for("kitchen.review", requirement_id=requirement_id))


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

    return render_template(
        "kitchen/review.html", requirement=req, items=data["items"], all_items=items,
        departments=departments, was_structured_file=was_structured_file,
        unmatched_count=unmatched_count,
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
    conn = g.conn
    try:
        confirm_kitchen_requirement(conn, g.user["id"], requirement_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("kitchen.review", requirement_id=requirement_id))
    flash("Requirement confirmed.", "success")
    return redirect(url_for("requirements.index"))
