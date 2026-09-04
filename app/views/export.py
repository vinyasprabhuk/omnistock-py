from __future__ import annotations

from flask import Blueprint, Response, g, request

from app.auth.page_branch import page_resolve_branch
from app.dates import date_key_to_db, today_key
from app.excel.export_workbook import (
    build_intent_workbook,
    build_kitchen_requirement_workbook,
    build_master_inventory_workbook,
    build_purchase_order_workbook,
    build_tracker_workbook,
)
from app.services.calculations import get_daily_tracker, get_low_stock, get_master_inventory
from app.services.kitchen_requirement import get_requirement_items_by_status
from app.services.intent import compute_recipe_prep

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
    requirement_id = request.args.get("requirementId") or None
    date_db = date_key_to_db(date)

    # Batch number for the filename comes from the *unfiltered* upload
    # order for the date, same ordinal the Requirements page shows --
    # computed even for a combined (non-batch-scoped) export so a
    # single-batch day's filename stays plain.
    all_items = get_requirement_items_by_status(g.conn, branch["branchId"], date_db, "ISSUED")
    batch_suffix = ""
    if requirement_id:
        seen_order = []
        for r in all_items:
            if r["requirementId"] not in seen_order:
                seen_order.append(r["requirementId"])
        if requirement_id in seen_order:
            batch_suffix = f"-batch{seen_order.index(requirement_id) + 1}"
        items = [r for r in all_items if r["requirementId"] == requirement_id]
    else:
        items = all_items

    departments: dict[str, list[dict]] = {}
    for r in items:
        departments.setdefault(r["departmentName"], []).append(r)
    department_sections = [
        {"departmentName": name, "items": sorted(rows, key=lambda i: i["itemName"])}
        for name, rows in departments.items()
    ]
    department_sections.sort(key=lambda s: s["departmentName"])

    data = build_kitchen_requirement_workbook(date, department_sections)
    return _xlsx_response(data, f"kitchen-requirement-{date}{batch_suffix}.xlsx")


@bp.route("/purchase-order")
def purchase_order():
    branch = page_resolve_branch(g.conn, g.user, request.args.get("branchId"))
    low_stock = get_low_stock(g.conn, branch["branchId"])
    rows = [
        {**r, "orderQty": round(max(r["opening"] - r["currentStock"], 0), 2)}
        for r in low_stock
    ]
    data = build_purchase_order_workbook(rows)
    return _xlsx_response(data, f"purchase-order-{today_key()}.xlsx")


@bp.route("/intent")
def intent():
    date = request.args.get("date") or today_key()
    branch = page_resolve_branch(g.conn, g.user, request.args.get("branchId"))
    intent_day = g.conn.execute(
        "SELECT id FROM IntentDay WHERE date = ? AND branchId = ?",
        (date_key_to_db(date), branch["branchId"]),
    ).fetchone()

    dish_counts, ingredients, recipe_prep = [], [], []
    if intent_day:
        dish_counts = [dict(r) for r in g.conn.execute(
            "SELECT dish.name AS dishName, dish.category AS category, idc.finalQty AS finalQty, idc.source AS source "
            "FROM IntentDishCount idc JOIN Dish dish ON dish.id = idc.dishId "
            "WHERE idc.intentDayId = ? ORDER BY idc.finalQty DESC", (intent_day["id"],),
        )]
        ingredients = [dict(r) for r in g.conn.execute(
            "SELECT ii.groupLabel AS groupLabel, item.name AS itemName, item.unit AS unit, ii.qty AS qty, ii.source AS source "
            "FROM IntentIngredient ii JOIN Item item ON item.id = ii.itemId "
            "WHERE ii.intentDayId = ? ORDER BY ii.groupLabel, ii.qty DESC", (intent_day["id"],),
        )]
        recipe_prep = compute_recipe_prep(g.conn, intent_day["id"])

    data = build_intent_workbook(date, dish_counts, recipe_prep, ingredients)
    return _xlsx_response(data, f"intent-{date}.xlsx")
