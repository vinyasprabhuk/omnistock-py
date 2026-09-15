from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.security import require_write
from app.services.calculations import get_daily_tracker
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
    """Admin-only: adds a correcting StockIssue entry for one item/date,
    the same real transaction manual Stock Issue entry (/issue) and the
    Kitchen Requirement Issue step both create -- so it shows up in the
    Issued column (and therefore Closing) through the exact same summed
    aggregate, no separate override field. Additive by design (a "top up"
    entry, not an overwrite) to match the existing convention for
    correcting historical data (see the real "Historical Import"
    department) rather than silently mutating someone else's real entry."""
    if g.user["role"] != "ADMIN":
        abort(403, "Only Admin can manually adjust the Issued column.")

    conn = g.conn
    date_key = request.form.get("date") or ""
    branch_id = request.form.get("branchId") or ""
    item_id = request.form.get("itemId") or ""
    department_name = (request.form.get("departmentName") or "").strip()
    qty_raw = request.form.get("qty") or ""

    redirect_to = url_for("tracker.index", date=date_key, branchId=branch_id)

    try:
        qty = float(qty_raw)
    except ValueError:
        qty = None

    if not department_name:
        flash("Department is required.", "error")
        return redirect(redirect_to)
    if qty is None or qty <= 0:
        flash("Enter a quantity greater than zero.", "error")
        return redirect(redirect_to)
    if not (date_key and branch_id and item_id):
        flash("Missing item, date, or branch.", "error")
        return redirect(redirect_to)

    create_stock_issue(conn, g.user["id"], branch_id, date_key, department_name,
                        [{"itemId": item_id, "qty": qty}])
    flash("Issued quantity added.", "success")
    return redirect(redirect_to)
