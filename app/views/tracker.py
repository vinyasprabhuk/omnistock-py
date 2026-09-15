from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.security import require_write
from app.services.calculations import get_daily_tracker, sum_issued
from app.services.transactions import create_stock_issue

bp = Blueprint("tracker", __name__)


@bp.route("/tracker")
def index():
    date = request.args.get("date") or today_key()
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(g.conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(g.conn) if is_admin else []

    rows = get_daily_tracker(g.conn, branch["branchId"], date_key_to_db(date))
    departments = [r["name"] for r in g.conn.execute(
        "SELECT name FROM Department WHERE active = 1 ORDER BY name ASC"
    )]

    return render_template(
        "tracker/index.html",
        date=date, branch=branch, is_admin=is_admin, branches=branches, rows=rows,
        departments=departments,
    )


@bp.route("/tracker/adjust-issued", methods=["POST"])
@require_write
def adjust_issued():
    """Admin-only: edits an item's Issued total for one date directly --
    the dialog pre-fills today's current total, and whatever the admin
    types becomes the new total (e.g. a wrong 500 typed as 0.5 actually
    lands on 0.5). Since Issued is a summed aggregate over however many
    real StockIssueItem rows exist for that item/date (not a single
    editable field), this is implemented by posting one more correcting
    StockIssueItem for the DIFFERENCE between the new and current total --
    the same real transaction manual Stock Issue entry (/issue) and the
    Kitchen Requirement Issue step both create, so it shows up in Issued/
    Closing through the exact same sum. That correction entry can be
    negative (reducing a wrongly-high total), matching the existing
    convention for fixing historical data (see the real "Historical
    Import" department) rather than mutating someone else's original row."""
    if g.user["role"] != "ADMIN":
        abort(403, "Only Admin can manually adjust the Issued column.")

    conn = g.conn
    date_key = request.form.get("date") or ""
    branch_id = request.form.get("branchId") or ""
    item_id = request.form.get("itemId") or ""
    department_name = (request.form.get("departmentName") or "").strip()
    new_total_raw = request.form.get("qty") or ""

    redirect_to = url_for("tracker.index", date=date_key, branchId=branch_id)

    try:
        new_total = float(new_total_raw)
    except ValueError:
        new_total = None

    if not department_name:
        flash("Department is required.", "error")
        return redirect(redirect_to)
    if new_total is None or new_total < 0:
        flash("Enter a valid quantity (zero or more).", "error")
        return redirect(redirect_to)
    if not (date_key and branch_id and item_id):
        flash("Missing item, date, or branch.", "error")
        return redirect(redirect_to)

    current_total = sum_issued(conn, item_id, branch_id, date_eq=date_key_to_db(date_key))
    delta = new_total - current_total
    if delta == 0:
        flash("Issued is already at that value.", "success")
        return redirect(redirect_to)

    create_stock_issue(conn, g.user["id"], branch_id, date_key, department_name,
                        [{"itemId": item_id, "qty": delta}])
    flash("Issued quantity updated.", "success")
    return redirect(redirect_to)
