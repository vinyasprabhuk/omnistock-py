from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.auth.session import ForbiddenError, resolve_branch_scope
from app.dates import date_key_to_db, today_key
from app.security import require_write
from app.services import production, wastage
from app.services.meal_periods import MEAL_LABELS, MEAL_PERIODS
from app.services.wastage_ingredients import compute_wasted_ingredients
from app.services.wastage_menu import get_wastage_menu
from app.services.wastage_variance import compute_variance

bp = Blueprint("wastage", __name__)

LOG_ROLES = ("KITCHEN", "ADMIN", "MANAGER", "DEPARTMENT_LEAD")


def _total_kg(entries: list[dict]) -> float:
    total = 0.0
    for e in entries:
        if e["weight"] is None:
            continue
        w = float(e["weight"])
        total += w / 1000 if e["unit"] == "GM" else w
    return total


@bp.route("/wastage")
def index():
    conn = g.conn
    date = request.args.get("date") or today_key()
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(conn) if is_admin else []

    can_log = g.user["role"] in LOG_ROLES
    can_see_analysis = g.user["role"] in ("ADMIN", "MANAGER")

    mode_param = request.args.get("mode")
    if mode_param == "variance" and can_see_analysis:
        mode = "variance"
    elif mode_param == "wastage":
        mode = "wastage"
    else:
        mode = "production"

    if mode == "wastage":
        entries = wastage.get_wastage_for_date(conn, branch["branchId"], date)
    else:
        entries = production.get_production_for_date(conn, branch["branchId"], date)
    menu = get_wastage_menu(conn)

    ingredients = compute_wasted_ingredients(conn, entries)
    entries = ingredients["entries"]  # same rows, each now carries matchedRecipeName/matchStatus

    grouped = {mp: [e for e in entries if e["mealPeriod"] == mp] for mp in MEAL_PERIODS}
    other = [e for e in entries if not e["mealPeriod"]]

    variance_rows, sales_available = [], True
    if can_see_analysis:
        variance = compute_variance(conn, date_key_to_db(date), branch["branchId"])
        variance_rows, sales_available = variance["rows"], variance["salesAvailable"]

    return render_template(
        "wastage/index.html", date=date, mode=mode, branch=branch, is_admin=is_admin,
        branches=branches, branch_param=branch_param or "", entries=entries, menu=menu,
        grouped=grouped, other=other, meal_labels=MEAL_LABELS, total_kg=_total_kg(entries),
        can_log=can_log, can_see_analysis=can_see_analysis,
        ingredient_lines=ingredients["lines"], ingredient_gaps=ingredients["gaps"],
        ingredient_total_spend=ingredients["totalSpend"],
        variance_rows=variance_rows, sales_available=sales_available,
    )


@bp.route("/wastage/create", methods=["POST"])
@require_write
def create():
    if g.user["role"] not in LOG_ROLES:
        abort(403, description="You don't have permission to log production/wastage entries")

    conn = g.conn
    mode = request.form.get("mode") or "production"
    user_branch_id = g.user.get("branchId")
    branch_id = user_branch_id or request.form.get("branchId")
    date_key = request.form.get("date") or today_key()
    meal_period = request.form.get("mealPeriod") or None
    dish = request.form.get("dish") or ""
    custom_name = request.form.get("customName") or ""
    description = dish or custom_name
    weight_raw = request.form.get("weight")
    unit = request.form.get("unit") or "KG"
    pieces_raw = request.form.get("pieces")
    photo = request.files.get("photo")

    try:
        weight = float(weight_raw) if weight_raw else None
        pieces = int(pieces_raw) if pieces_raw else None
        photo_bytes = photo.read() if photo and photo.filename else b""
        fn = photo.filename if photo else ""
        mime = photo.mimetype if photo else None

        if mode == "wastage":
            wastage.create_wastage(conn, g.user["id"], branch_id, date_key, meal_period,
                                    description, weight, unit, pieces, photo_bytes, fn, mime)
        else:
            production.create_production(conn, g.user["id"], branch_id, date_key, meal_period,
                                          description, weight, unit, pieces, photo_bytes, fn, mime)
        flash(f"{description} logged.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("wastage.index", date=date_key, mode=mode, branchId=branch_id))


@bp.route("/wastage/<entry_id>/delete", methods=["POST"])
@require_write
def delete(entry_id: str):
    conn = g.conn
    mode = request.form.get("mode") or "production"
    date_key = request.form.get("date") or today_key()
    branch_id = request.form.get("branchId") or ""

    getter = wastage.get_branch_id if mode == "wastage" else production.get_branch_id
    deleter = wastage.delete_wastage if mode == "wastage" else production.delete_production

    entry_branch_id = getter(conn, entry_id)
    if entry_branch_id is None:
        flash("Entry not found.", "error")
        return redirect(url_for("wastage.index", date=date_key, mode=mode, branchId=branch_id))
    try:
        resolve_branch_scope(g.user, entry_branch_id)
    except ForbiddenError:
        flash("You don't have access to that entry.", "error")
        return redirect(url_for("wastage.index", date=date_key, mode=mode, branchId=branch_id))

    deleter(conn, entry_id)
    flash("Entry deleted.", "success")
    return redirect(url_for("wastage.index", date=date_key, mode=mode, branchId=branch_id))
