from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin
from app.security import require_write
from app.services.excel_upload import commit_stock_issue_excel, preview_stock_issue_excel
from app.services.transactions import create_stock_issue

bp = Blueprint("issue", __name__)


@bp.route("/issue", methods=["GET"])
def index():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    items = [dict(r) for r in conn.execute(
        "SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC"
    )]
    departments = [r["name"] for r in conn.execute(
        "SELECT name FROM Department WHERE active = 1 ORDER BY name ASC"
    )]
    branches = list_branches_for_admin(conn) if not user_branch_id else []
    return render_template(
        "issue/index.html", items=items, departments=departments,
        branches=branches, user_branch_id=user_branch_id,
    )


@bp.route("/issue", methods=["POST"])
@require_write
def create():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    date_key = request.form.get("date") or ""
    branch_id = user_branch_id or request.form.get("branchId")
    department_name = (request.form.get("departmentName") or "").strip()

    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")

    lines = []
    for item_id, qty in zip(item_ids, qtys):
        if item_id and qty:
            try:
                lines.append({"itemId": item_id, "qty": float(qty)})
            except ValueError:
                continue

    if not lines:
        flash("Add at least one line item with an item and quantity.", "error")
        return redirect(url_for("issue.index"))
    if not department_name:
        flash("Department is required.", "error")
        return redirect(url_for("issue.index"))
    if not branch_id:
        flash("Select a branch first.", "error")
        return redirect(url_for("issue.index"))
    if not date_key:
        flash("Date is required.", "error")
        return redirect(url_for("issue.index"))

    create_stock_issue(conn, g.user["id"], branch_id, date_key, department_name, lines)
    flash("Stock issue saved.", "success")
    return redirect(url_for("issue.index"))


@bp.route("/issue/preview", methods=["POST"])
@require_write
def preview():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a file first.", "error")
        return redirect(url_for("issue.index"))

    rows = preview_stock_issue_excel(conn, file.read(), file.filename)
    branches = list_branches_for_admin(conn) if not user_branch_id else []
    items = [dict(r) for r in conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC")]

    return render_template(
        "issue/preview.html", rows=rows, items=items, branches=branches,
        user_branch_id=user_branch_id, date=request.form.get("date", ""),
    )


@bp.route("/issue/commit", methods=["POST"])
@require_write
def commit():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    date_key = request.form.get("date") or ""
    branch_id = user_branch_id or request.form.get("branchId")

    department_names = request.form.getlist("departmentName")
    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")

    rows = []
    for dept, item_id, qty in zip(department_names, item_ids, qtys):
        if item_id and qty:
            try:
                rows.append({"departmentName": dept, "itemId": item_id, "qty": float(qty)})
            except ValueError:
                continue

    if not rows or not branch_id or not date_key:
        flash("Every row needs a matched item and quantity before confirming.", "error")
        return redirect(url_for("issue.index"))

    result = commit_stock_issue_excel(conn, g.user["id"], branch_id, date_key, rows)
    flash(f"Saved stock issue across {result['departmentsCreated']} department(s).", "success")
    return redirect(url_for("issue.index"))
