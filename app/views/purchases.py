from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin
from app.security import require_write
from app.services.excel_upload import commit_purchase_excel, preview_purchase_excel
from app.services.transactions import attach_purchase_receipt, create_purchase

bp = Blueprint("purchases", __name__)


@bp.route("/purchases", methods=["GET"])
def index():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    items = [dict(r) for r in conn.execute(
        "SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC"
    )]
    branches = list_branches_for_admin(conn) if not user_branch_id else []
    return render_template("purchases/index.html", items=items, branches=branches, user_branch_id=user_branch_id)


@bp.route("/purchases", methods=["POST"])
@require_write
def create():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    date_key = request.form.get("date") or ""
    branch_id = user_branch_id or request.form.get("branchId")
    supplier = (request.form.get("supplier") or "").strip() or None

    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")
    rates = request.form.getlist("rate")

    lines = []
    for item_id, qty, rate in zip(item_ids, qtys, rates):
        if item_id and qty:
            try:
                lines.append({"itemId": item_id, "qty": float(qty), "rate": float(rate or 0)})
            except ValueError:
                continue

    if not lines:
        flash("Add at least one line item with an item and quantity.", "error")
        return redirect(url_for("purchases.index"))
    if not branch_id:
        flash("Select a branch first.", "error")
        return redirect(url_for("purchases.index"))
    if not date_key:
        flash("Date is required.", "error")
        return redirect(url_for("purchases.index"))

    purchase_id = create_purchase(conn, g.user["id"], branch_id, date_key, supplier, lines)

    receipt = request.files.get("receipt")
    if receipt and receipt.filename:
        attach_purchase_receipt(conn, purchase_id, receipt.read(), receipt.filename, receipt.mimetype)

    flash("Purchase saved.", "success")
    return redirect(url_for("purchases.index"))


@bp.route("/purchases/preview", methods=["POST"])
@require_write
def preview():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a file first.", "error")
        return redirect(url_for("purchases.index"))

    rows = preview_purchase_excel(conn, file.read(), file.filename)
    items = [dict(r) for r in conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC")]
    branches = list_branches_for_admin(conn) if not user_branch_id else []

    return render_template(
        "purchases/preview.html", rows=rows, items=items, branches=branches,
        user_branch_id=user_branch_id, date=request.form.get("date", ""),
    )


@bp.route("/purchases/commit", methods=["POST"])
@require_write
def commit():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    date_key = request.form.get("date") or ""
    branch_id = user_branch_id or request.form.get("branchId")
    supplier = (request.form.get("supplier") or "").strip() or None

    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")
    rates = request.form.getlist("rate")

    rows = []
    for item_id, qty, rate in zip(item_ids, qtys, rates):
        if item_id and qty:
            try:
                rows.append({"itemId": item_id, "qty": float(qty), "rate": float(rate or 0)})
            except ValueError:
                continue

    if not rows or not branch_id or not date_key:
        flash("Every row needs a matched item and quantity before confirming.", "error")
        return redirect(url_for("purchases.index"))

    result = commit_purchase_excel(conn, g.user["id"], branch_id, date_key, supplier, rows)
    flash(f"Saved {result['itemsCreated']} purchase line item(s).", "success")
    return redirect(url_for("purchases.index"))
