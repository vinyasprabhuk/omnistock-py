from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin
from app.security import require_write
from app.services.excel_upload import commit_purchase_excel, preview_purchase_excel
from app.services.purchase_webhook import (
    approve_webhook_event,
    get_pending_webhook_events,
    get_webhook_event_for_review,
    reject_webhook_event,
)
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
    pending_webhook_count = len(get_pending_webhook_events(conn))
    return render_template("purchases/index.html", items=items, branches=branches,
                            user_branch_id=user_branch_id, pending_webhook_count=pending_webhook_count)


@bp.route("/purchases", methods=["POST"])
@require_write
def create():
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    date_key = request.form.get("date") or ""
    branch_id = user_branch_id or request.form.get("branchId")
    supplier = (request.form.get("supplier") or "").strip() or None
    gst_number = (request.form.get("gstNumber") or "").strip() or None
    bill_no = (request.form.get("billNo") or "").strip() or None

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

    purchase_id = create_purchase(conn, g.user["id"], branch_id, date_key, supplier, lines,
                                   gst_number=gst_number, bill_no=bill_no)

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
    gst_number = (request.form.get("gstNumber") or "").strip() or None
    bill_no = (request.form.get("billNo") or "").strip() or None

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

    result = commit_purchase_excel(conn, g.user["id"], branch_id, date_key, supplier, rows,
                                    gst_number=gst_number, bill_no=bill_no)
    flash(f"Saved {result['itemsCreated']} purchase line item(s).", "success")
    return redirect(url_for("purchases.index"))


@bp.route("/purchases/incoming", methods=["GET"])
def incoming():
    events = get_pending_webhook_events(g.conn)
    return render_template("purchases/incoming.html", events=events)


@bp.route("/purchases/incoming/<event_id>", methods=["GET"])
def incoming_review(event_id: str):
    conn = g.conn
    event = get_webhook_event_for_review(conn, event_id)
    if event is None:
        flash("That invoice event was not found.", "error")
        return redirect(url_for("purchases.incoming"))
    user_branch_id = g.user.get("branchId")
    branches = list_branches_for_admin(conn) if not user_branch_id else []
    all_items = [dict(r) for r in conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC")]
    return render_template(
        "purchases/incoming_review.html", event=event, all_items=all_items,
        branches=branches, user_branch_id=user_branch_id,
    )


@bp.route("/purchases/incoming/<event_id>/approve", methods=["POST"])
@require_write
def incoming_approve(event_id: str):
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    branch_id = user_branch_id or request.form.get("branchId")

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

    if not branch_id:
        flash("Select a branch first.", "error")
        return redirect(url_for("purchases.incoming_review", event_id=event_id))

    try:
        approve_webhook_event(conn, g.user["id"], event_id, branch_id, lines)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("purchases.incoming_review", event_id=event_id))

    flash("Invoice approved and saved as a Purchase.", "success")
    return redirect(url_for("purchases.incoming"))


@bp.route("/purchases/incoming/<event_id>/reject", methods=["POST"])
@require_write
def incoming_reject(event_id: str):
    reason = request.form.get("reason") or ""
    try:
        reject_webhook_event(g.conn, g.user["id"], event_id, reason)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("purchases.incoming_review", event_id=event_id))

    flash("Invoice rejected.", "success")
    return redirect(url_for("purchases.incoming"))
