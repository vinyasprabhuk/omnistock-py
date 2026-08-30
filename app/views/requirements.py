from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.security import require_write
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

    # Grand total per item, across every batch uploaded for this date --
    # shown as a badge so a split across two uploads is still visible at a
    # glance without merging the rows themselves.
    totals_by_item: dict[str, float] = {}
    for r in items:
        totals_by_item[r["itemId"]] = totals_by_item.get(r["itemId"], 0.0) + r["qty"]

    # Rows already come back ordered by requirementCreatedAt (see
    # get_confirmed_requirement_items), so the first requirementId
    # encountered is batch 1, the next distinct one is batch 2, etc. --
    # each kitchen upload for the date stays its own section instead of
    # its items silently interleaving with another upload's under the
    # same department card.
    batch_numbers: dict[str, int] = {}
    batches: list[dict] = []
    for r in items:
        req_id = r["requirementId"]
        if req_id not in batch_numbers:
            batch_numbers[req_id] = len(batches) + 1
            batches.append({"batchNumber": batch_numbers[req_id], "departments": {}})
        batch = batches[batch_numbers[req_id] - 1]
        batch["departments"].setdefault(r["departmentName"], []).append({
            **r, "total": totals_by_item[r["itemId"]],
        })

    for batch in batches:
        department_sections = [
            {"departmentName": name, "items": sorted(rows, key=lambda i: i["itemName"])}
            for name, rows in batch["departments"].items()
        ]
        department_sections.sort(key=lambda s: s["departmentName"])
        batch["departmentSections"] = department_sections
        del batch["departments"]

    return render_template(
        "requirements/index.html",
        date=date, branch=branch, is_admin=is_admin, branches=branches,
        items=items, batches=batches,
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
