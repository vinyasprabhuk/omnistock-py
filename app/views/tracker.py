from __future__ import annotations

from flask import Blueprint, g, render_template, request

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.services.calculations import get_daily_tracker

bp = Blueprint("tracker", __name__)


@bp.route("/tracker")
def index():
    date = request.args.get("date") or today_key()
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(g.conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(g.conn) if is_admin else []

    rows = get_daily_tracker(g.conn, branch["branchId"], date_key_to_db(date))

    return render_template(
        "tracker/index.html",
        date=date, branch=branch, is_admin=is_admin, branches=branches, rows=rows,
    )
