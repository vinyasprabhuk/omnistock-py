from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.security import require_write
from app.services.calculations import get_master_inventory
from app.services.kitchen_requirement import get_confirmed_requirement_items, update_confirmed_requirement_item_qty

bp = Blueprint("requirements", __name__)


@bp.route("/requirements")
def index():
    date = request.args.get("date") or today_key()
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(g.conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(g.conn) if is_admin else []

    date_db = date_key_to_db(date)
    items = get_confirmed_requirement_items(g.conn, branch["branchId"], date_db)
    stock_by_item = {r["itemId"]: r["currentStock"] for r in get_master_inventory(g.conn, branch["branchId"], date_db)}

    totals_by_item: dict[str, float] = {}
    for r in items:
        totals_by_item[r["itemId"]] = totals_by_item.get(r["itemId"], 0.0) + r["qty"]

    departments: dict[str, list[dict]] = {}
    for r in items:
        departments.setdefault(r["departmentName"], []).append({
            **r, "total": totals_by_item[r["itemId"]], "currentStock": stock_by_item.get(r["itemId"], 0.0),
        })
    department_sections = [
        {"departmentName": name, "items": sorted(rows, key=lambda i: i["itemName"])}
        for name, rows in departments.items()
    ]
    department_sections.sort(key=lambda s: s["departmentName"])

    return render_template(
        "requirements/index.html",
        date=date, branch=branch, is_admin=is_admin, branches=branches,
        items=items, department_sections=department_sections,
    )


@bp.route("/requirements/item/<item_id>/update", methods=["POST"])
@require_write
def update_item(item_id: str):
    date = request.form.get("date") or today_key()
    branch_id = request.form.get("branchId") or ""
    qty = request.form.get("qty")
    try:
        update_confirmed_requirement_item_qty(g.conn, item_id, float(qty))
    except (ValueError, TypeError) as e:
        flash(str(e), "error")
    return redirect(url_for("requirements.index", date=date, branchId=branch_id))
