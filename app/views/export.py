from __future__ import annotations

from flask import Blueprint, Response, g, request

from app.auth.page_branch import page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.excel.export_workbook import (
    build_consolidated_requirement_workbook,
    build_master_inventory_workbook,
    build_tracker_workbook,
)
from app.services.calculations import get_consolidated_requirement, get_daily_tracker, get_master_inventory

bp = Blueprint("export", __name__, url_prefix="/api/export")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(
        data, mimetype=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/tracker")
def tracker():
    date = request.args.get("date") or today_key()
    branch = page_resolve_branch(g.conn, g.user, request.args.get("branchId"))
    rows = get_daily_tracker(g.conn, branch["branchId"], date_key_to_db(date))
    data = build_tracker_workbook(date, rows)
    return _xlsx_response(data, f"daily-tracker-{date}.xlsx")


@bp.route("/inventory")
def inventory():
    branch = page_resolve_branch(g.conn, g.user, request.args.get("branchId"))
    rows = get_master_inventory(g.conn, branch["branchId"])
    data = build_master_inventory_workbook(rows)
    return _xlsx_response(data, "master-inventory.xlsx")


@bp.route("/requirements")
def requirements():
    date = request.args.get("date") or today_key()
    branch = page_resolve_branch(g.conn, g.user, request.args.get("branchId"))
    rows = get_consolidated_requirement(g.conn, branch["branchId"], date_eq=date_key_to_db(date))
    data = build_consolidated_requirement_workbook(date, rows)
    return _xlsx_response(data, f"kitchen-requirement-{date}.xlsx")
