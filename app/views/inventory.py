from __future__ import annotations

from flask import Blueprint, g, render_template, request

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.services.calculations import get_master_inventory

bp = Blueprint("inventory", __name__)


@bp.route("/inventory")
def index():
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(g.conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(g.conn) if is_admin else []

    rows = get_master_inventory(g.conn, branch["branchId"])
    total_store_value = sum(r["storeValue"] for r in rows)

    return render_template(
        "inventory/index.html",
        branch=branch, is_admin=is_admin, branches=branches, rows=rows,
        total_store_value=total_store_value,
    )
