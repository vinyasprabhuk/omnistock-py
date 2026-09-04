from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.security import require_write
from app.services.kitchen_requirement import (
    edit_approved_requirement_qty,
    get_action_dates_for_branch,
    get_pending_requirements_for_branch_date,
    get_requirement_items_by_status,
)

bp = Blueprint("requirements", __name__)


def _group_into_batches(items: list[dict]) -> list[dict]:
    """Rows come back ordered by requirementCreatedAt (see
    get_requirement_items_by_status), so the first requirementId
    encountered is batch 1, the next distinct one is batch 2, etc. --
    each requirement stays its own section instead of its items silently
    interleaving with another requirement's under the same department
    card."""
    batch_numbers: dict[str, int] = {}
    batches: list[dict] = []
    for r in items:
        req_id = r["requirementId"]
        if req_id not in batch_numbers:
            batch_numbers[req_id] = len(batches) + 1
            batches.append({
                "batchNumber": batch_numbers[req_id], "requirementId": req_id,
                "requestType": r["requestType"],
                "confirmedByName": r["confirmedByName"] or r["confirmedById"], "confirmedAt": r["confirmedAt"],
                "issuedByName": r.get("issuedByName") or r.get("issuedById"), "issuedAt": r.get("issuedAt"),
                "departments": {},
            })
        batch = batches[batch_numbers[req_id] - 1]
        batch["departments"].setdefault(r["departmentName"], []).append(r)

    for batch in batches:
        department_sections = [
            {"departmentName": name, "items": sorted(rows, key=lambda i: i["itemName"])}
            for name, rows in batch["departments"].items()
        ]
        department_sections.sort(key=lambda s: s["departmentName"])
        batch["departmentSections"] = department_sections
        del batch["departments"]
    return batches


@bp.route("/requirements")
def index():
    date = request.args.get("date") or today_key()
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(g.conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(g.conn) if is_admin else []

    date_db = date_key_to_db(date)
    can_review = g.user["role"] in ("ADMIN", "MANAGER")
    pending = get_pending_requirements_for_branch_date(g.conn, branch["branchId"], date_db) if can_review else []

    approved_items = get_requirement_items_by_status(g.conn, branch["branchId"], date_db, "APPROVED")
    issued_items = get_requirement_items_by_status(g.conn, branch["branchId"], date_db, "ISSUED")
    approved_batches = _group_into_batches(approved_items)
    issued_batches = _group_into_batches(issued_items)

    action_dates = get_action_dates_for_branch(g.conn, branch["branchId"]) if can_review else []
    other_action_dates = [d for d in action_dates if d["dateKey"] != date]

    return render_template(
        "requirements/index.html",
        date=date, branch=branch, is_admin=is_admin, branches=branches,
        approved_batches=approved_batches, issued_batches=issued_batches,
        pending=pending, can_review=can_review, other_action_dates=other_action_dates,
    )


@bp.route("/requirements/item/<item_id>/update", methods=["POST"])
@require_write
def update_item(item_id: str):
    date = request.form.get("date") or today_key()
    branch_id = request.form.get("branchId") or ""
    qty = request.form.get("qty")
    try:
        edit_approved_requirement_qty(g.conn, item_id, float(qty))
    except (ValueError, TypeError) as e:
        flash(str(e), "error")
    return redirect(url_for("requirements.index", date=date, branchId=branch_id))
