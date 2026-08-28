from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import from_db, to_db, today_key
from app.security import require_write
from app.services.dish_sales_loader import load_dish_sales_file
from app.services.intent import compute_recipe_prep, generate_intent_day, set_dish_override

bp = Blueprint("intent", __name__)

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _week_start(date_key: str):
    d = from_db(to_db_key(date_key))
    return d - timedelta(days=d.weekday())


def to_db_key(date_key: str) -> str:
    from app.dates import date_key_to_db
    return date_key_to_db(date_key)


@bp.route("/intent", methods=["GET"])
def index():
    conn = g.conn
    branch = page_resolve_branch(conn, g.user, request.args.get("branchId"))
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(conn) if is_admin else []

    week_param = request.args.get("week") or today_key()
    week_monday = _week_start(week_param)
    week_dates = [week_monday + timedelta(days=i) for i in range(7)]
    week_date_keys = [d.strftime("%Y-%m-%d") for d in week_dates]

    day_param = request.args.get("day") or today_key()
    if day_param not in week_date_keys:
        day_param = week_date_keys[0]

    days_info = []
    for i, dk in enumerate(week_date_keys):
        row = conn.execute(
            "SELECT id, status FROM IntentDay WHERE date = ? AND branchId = ?",
            (to_db_key(dk), branch["branchId"]),
        ).fetchone()
        days_info.append({
            "dateKey": dk, "label": WEEKDAY_LABELS[i],
            "display": week_dates[i].strftime("%d %b"),
            "status": row["status"] if row else "NONE",
            "intentDayId": row["id"] if row else None,
        })

    selected = next(d for d in days_info if d["dateKey"] == day_param)
    intent_day = None
    dish_counts = []
    ingredients = []
    recipe_prep = []
    if selected["intentDayId"]:
        intent_day = conn.execute("SELECT * FROM IntentDay WHERE id = ?", (selected["intentDayId"],)).fetchone()
        dish_counts = conn.execute(
            "SELECT idc.*, dish.name AS dishName, dish.category AS category "
            "FROM IntentDishCount idc JOIN Dish dish ON dish.id = idc.dishId "
            "WHERE idc.intentDayId = ? ORDER BY idc.finalQty DESC",
            (selected["intentDayId"],),
        ).fetchall()
        ingredients = conn.execute(
            "SELECT ii.*, item.name AS itemName, item.unit AS unit "
            "FROM IntentIngredient ii JOIN Item item ON item.id = ii.itemId "
            "WHERE ii.intentDayId = ? ORDER BY ii.groupLabel, ii.qty DESC",
            (selected["intentDayId"],),
        ).fetchall()
        recipe_prep = compute_recipe_prep(conn, selected["intentDayId"])

    prev_week = (week_monday - timedelta(days=7)).strftime("%Y-%m-%d")
    next_week = (week_monday + timedelta(days=7)).strftime("%Y-%m-%d")
    dish_categories = sorted({dc["category"] for dc in dish_counts})
    recipe_groups = sorted({ing["groupLabel"] for ing in ingredients})

    return render_template(
        "intent/index.html", branch=branch, is_admin=is_admin, branches=branches,
        days_info=days_info, selected=selected, week_label=f"{week_dates[0].strftime('%d %b')} - {week_dates[6].strftime('%d %b %Y')}",
        prev_week=prev_week, next_week=next_week, intent_day=intent_day,
        dish_counts=dish_counts, ingredients=ingredients, recipe_prep=recipe_prep,
        dish_categories=dish_categories, recipe_groups=recipe_groups,
    )


@bp.route("/intent/generate", methods=["POST"])
@require_write
def generate():
    conn = g.conn
    branch_id = request.form.get("branchId") or g.user.get("branchId")
    date_key = request.form.get("date")
    week = request.form.get("week") or date_key
    if not branch_id or not date_key:
        flash("Missing branch or date.", "error")
        return redirect(url_for("intent.index"))

    result = generate_intent_day(conn, date_key, branch_id)
    conn.commit()
    if result["gaps"]:
        flash(f"Generated with {len(result['gaps'])} gaps (missing recipes) -- see the ingredient list for what's covered.", "message")
    else:
        flash("Generated.", "success")
    return redirect(url_for("intent.index", week=week, day=date_key, branchId=branch_id))


@bp.route("/intent/<intent_day_id>/dish/<dish_id>/override", methods=["POST"])
@require_write
def override_dish(intent_day_id: str, dish_id: str):
    conn = g.conn
    qty = request.form.get("finalQty")
    week = request.form.get("week")
    day = request.form.get("day")
    branch_id = request.form.get("branchId")
    try:
        set_dish_override(conn, intent_day_id, dish_id, float(qty))
        conn.commit()
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("intent.index", week=week, day=day, branchId=branch_id))


@bp.route("/intent/<intent_day_id>/ingredient/<ingredient_id>/update", methods=["POST"])
@require_write
def update_ingredient(intent_day_id: str, ingredient_id: str):
    conn = g.conn
    qty = request.form.get("qty")
    week = request.form.get("week")
    day = request.form.get("day")
    branch_id = request.form.get("branchId")
    try:
        from app.dates import now_db
        conn.execute(
            "UPDATE IntentIngredient SET qty = ?, source = 'EDITED', updatedAt = ? WHERE id = ? AND intentDayId = ?",
            (float(qty), now_db(), ingredient_id, intent_day_id),
        )
        conn.commit()
    except ValueError:
        flash("Invalid quantity.", "error")
    return redirect(url_for("intent.index", week=week, day=day, branchId=branch_id))


@bp.route("/intent/<intent_day_id>/confirm", methods=["POST"])
@require_write
def confirm(intent_day_id: str):
    conn = g.conn
    week = request.form.get("week")
    day = request.form.get("day")
    branch_id = request.form.get("branchId")
    from app.dates import now_db
    conn.execute(
        "UPDATE IntentDay SET status = 'CONFIRMED', confirmedAt = ?, confirmedByUserId = ?, updatedAt = ? WHERE id = ?",
        (now_db(), g.user["id"], now_db(), intent_day_id),
    )
    conn.commit()
    flash("Day confirmed.", "success")
    return redirect(url_for("intent.index", week=week, day=day, branchId=branch_id))


@bp.route("/intent/upload-sales", methods=["POST"])
@require_write
def upload_sales():
    conn = g.conn
    week = request.form.get("week") or today_key()
    branch_id = request.form.get("branchId")
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        flash("Choose at least one day-wise sale report file.", "error")
        return redirect(url_for("intent.index", week=week, branchId=branch_id))

    total_rows = 0
    total_dishes = 0
    dates_loaded: list[str] = []
    errors: list[str] = []

    for file in files:
        if not file.filename.lower().endswith((".xlsx", ".xls")):
            errors.append(f"{file.filename}: not an .xlsx/.xls file")
            continue
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)
        try:
            result = load_dish_sales_file(conn, str(tmp_path), file.filename)
            if result["date"] is None:
                errors.append(f"{file.filename}: no sale rows found -- check it's the real export format")
                continue
            total_rows += result["rowsLoaded"]
            total_dishes += result["dishesCreated"]
            dates_loaded.append(result["date"])
        except Exception as e:
            errors.append(f"{file.filename}: {e}")
        finally:
            tmp_path.unlink(missing_ok=True)

    conn.commit()

    if dates_loaded:
        flash(
            f"Loaded {len(dates_loaded)} day(s) ({', '.join(sorted(dates_loaded))}), "
            f"{total_rows} sale rows, {total_dishes} new dishes discovered.",
            "success",
        )
    if errors:
        flash(f"{len(errors)} file(s) skipped: {'; '.join(errors)}", "error")

    return redirect(url_for("intent.index", week=week, branchId=branch_id))
