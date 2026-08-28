from __future__ import annotations

from flask import Blueprint, g, render_template, request

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.services.calculations import get_consolidated_requirement

bp = Blueprint("requirements", __name__)


@bp.route("/requirements")
def index():
    date = request.args.get("date") or today_key()
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(g.conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(g.conn) if is_admin else []

    rows = get_consolidated_requirement(g.conn, branch["branchId"], date_eq=date_key_to_db(date))

    departments: dict[str, list[dict]] = {}
    for row in rows:
        for d in row["byDepartment"]:
            departments.setdefault(d["departmentName"], []).append({
                "itemId": row["itemId"], "itemName": row["itemName"], "unit": row["unit"],
                "qty": d["qty"], "total": row["total"],
            })
    department_sections = [
        {"departmentName": name, "items": sorted(items, key=lambda i: i["itemName"])}
        for name, items in departments.items()
    ]
    department_sections.sort(key=lambda s: s["departmentName"])

    return render_template(
        "requirements/index.html",
        date=date, branch=branch, is_admin=is_admin, branches=branches,
        rows=rows, department_sections=department_sections,
    )
