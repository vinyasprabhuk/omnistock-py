"""Admin section: hub, items, branches/departments, users, wastage menu,
status healthcheck. Branding lives in admin_branding.py. Legacy import in
admin_import.py. Every route here requires ADMIN (enforced twice: the
before_request RBAC in app/__init__.py already blocks non-admins from any
/admin/* path, and @require_role("ADMIN") here is defense in depth /
explicit self-documentation)."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.security import require_role
from app.services import admin as admin_service
from app.services import branding as branding_service
from app.services.excel_upload import commit_opening_stock_excel, preview_opening_stock_excel
from app.services.excel_import import commit_excel_import, preview_excel_import
from app.services.wastage_menu import create_wastage_menu_item, delete_wastage_menu_item, get_all_wastage_menu_items
from app.services.meal_periods import MEAL_LABELS, MEAL_PERIODS

bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLES = ["ADMIN", "MANAGER", "STORE", "KITCHEN", "VIEWER"]

THEME_COLOR_SWATCH = {
    "navy": "#0b1f44", "neutral": "#71717a", "blue": "#2563eb", "green": "#16a34a",
    "rose": "#e11d48", "orange": "#f97316", "purple": "#7c3aed",
}
THEME_COLOR_LABEL = {
    "navy": "Navy (Enterprise)", "neutral": "Neutral", "blue": "Blue", "green": "Green",
    "rose": "Rose", "orange": "Orange", "purple": "Purple",
}
THEME_MODE_LABEL = {"light": "Light", "dark": "Dark", "system": "Match device"}
BRAND_SIZE_LABEL = {"sm": "Small", "md": "Medium", "lg": "Large"}


@bp.route("")
@require_role("ADMIN")
def hub():
    links = [
        {"href": "/admin/items", "label": "Item Master", "desc": "Items, units, prices, aliases"},
        {"href": "/admin/branches", "label": "Branches & Departments", "desc": "Manage locations and kitchen sections"},
        {"href": "/admin/wastage-menu", "label": "Wastage Menu", "desc": "Add or remove the dish buttons on the Wastage page"},
        {"href": "/admin/users", "label": "Users", "desc": "Create logins, assign roles and branches"},
        {"href": "/admin/status", "label": "System Status", "desc": "Database health check"},
        {"href": "/admin/import", "label": "Import Existing Excel", "desc": "One-time import from your old workbook"},
        {"href": "/admin/branding", "label": "Branding", "desc": "App name, logo, and theme"},
    ]
    return render_template("admin/hub.html", links=links)


# --- Items ---

@bp.route("/items")
@require_role("ADMIN")
def items():
    conn = g.conn
    branches = [dict(r) for r in conn.execute("SELECT id, name FROM Branch WHERE active = 1 ORDER BY name ASC")]
    branch_id = request.args.get("branchId") or (branches[0]["id"] if branches else "")

    item_rows = conn.execute("SELECT * FROM Item WHERE active = 1 ORDER BY name ASC").fetchall()
    item_list = [dict(r) for r in item_rows]
    for item in item_list:
        aliases = conn.execute("SELECT id, alias FROM ItemAlias WHERE itemId = ?", (item["id"],)).fetchall()
        item["aliases"] = [dict(a) for a in aliases]

    opening = conn.execute("SELECT itemId, qty FROM ItemOpeningStock WHERE branchId = ?", (branch_id,)).fetchall()
    opening_by_item = {r["itemId"]: r["qty"] for r in opening}

    return render_template("admin/items.html", branches=branches, branch_id=branch_id,
                            items=item_list, opening_by_item=opening_by_item)


@bp.route("/items/create", methods=["POST"])
@require_role("ADMIN")
def items_create():
    conn = g.conn
    admin_service.create_item(
        conn, request.form.get("name", ""), request.form.get("unit", ""),
        float(request.form.get("purchasePrice") or 0), float(request.form.get("openingStock") or 0),
        request.form.get("branchId", ""), request.form.get("category") or None,
    )
    flash("Item added.", "success")
    return redirect(url_for("admin.items", branchId=request.form.get("branchId")))


@bp.route("/items/opening-stock", methods=["POST"])
@require_role("ADMIN")
def items_opening_stock():
    conn = g.conn
    admin_service.set_opening_stock(conn, request.form["itemId"], request.form["branchId"], float(request.form.get("qty") or 0))
    flash("Opening stock updated.", "success")
    return redirect(url_for("admin.items", branchId=request.form.get("branchId")))


@bp.route("/items/<item_id>/alias", methods=["POST"])
@require_role("ADMIN")
def items_add_alias(item_id: str):
    conn = g.conn
    admin_service.add_item_alias(conn, item_id, request.form.get("alias", ""))
    flash("Alias added.", "success")
    return redirect(url_for("admin.items", branchId=request.form.get("branchId")))


@bp.route("/items/<item_id>/deactivate", methods=["POST"])
@require_role("ADMIN")
def items_deactivate(item_id: str):
    conn = g.conn
    admin_service.deactivate_item(conn, item_id)
    flash("Item deactivated.", "success")
    return redirect(url_for("admin.items", branchId=request.form.get("branchId")))


@bp.route("/items/opening-stock/preview", methods=["POST"])
@require_role("ADMIN")
def items_opening_stock_preview():
    conn = g.conn
    branch_id = request.form.get("branchId", "")
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a file first.", "error")
        return redirect(url_for("admin.items", branchId=branch_id))
    rows = preview_opening_stock_excel(conn, file.read())
    items_list = [dict(r) for r in conn.execute("SELECT id, name, unit FROM Item WHERE active = 1 ORDER BY name ASC")]
    return render_template("admin/opening_stock_preview.html", rows=rows, items=items_list, branch_id=branch_id)


@bp.route("/items/opening-stock/commit", methods=["POST"])
@require_role("ADMIN")
def items_opening_stock_commit():
    conn = g.conn
    branch_id = request.form.get("branchId", "")
    item_ids = request.form.getlist("itemId")
    qtys = request.form.getlist("qty")
    rows = []
    for item_id, qty in zip(item_ids, qtys):
        if item_id and qty:
            try:
                rows.append({"itemId": item_id, "qty": float(qty)})
            except ValueError:
                continue
    result = commit_opening_stock_excel(conn, branch_id, rows)
    flash(f"Updated opening stock for {result['updated']} item(s).", "success")
    return redirect(url_for("admin.items", branchId=branch_id))


# --- Branches & Departments ---

@bp.route("/branches")
@require_role("ADMIN")
def branches():
    conn = g.conn
    branch_rows = [dict(r) for r in conn.execute("SELECT id, name FROM Branch WHERE active = 1 ORDER BY name ASC")]
    dept_rows = conn.execute("SELECT id, name FROM Department WHERE active = 1 ORDER BY name ASC").fetchall()
    departments = []
    for d in dept_rows:
        kri_count = conn.execute("SELECT COUNT(*) FROM KitchenRequirementItem WHERE departmentId = ?", (d["id"],)).fetchone()[0]
        si_count = conn.execute("SELECT COUNT(*) FROM StockIssue WHERE departmentId = ?", (d["id"],)).fetchone()[0]
        departments.append({"id": d["id"], "name": d["name"], "inUseCount": kri_count + si_count})
    return render_template("admin/branches.html", branches=branch_rows, departments=departments)


@bp.route("/branches/create", methods=["POST"])
@require_role("ADMIN")
def branches_create():
    admin_service.create_branch(g.conn, request.form.get("name", ""))
    flash("Branch added.", "success")
    return redirect(url_for("admin.branches"))


@bp.route("/branches/<branch_id>/rename", methods=["POST"])
@require_role("ADMIN")
def branches_rename(branch_id: str):
    try:
        admin_service.rename_branch(g.conn, branch_id, request.form.get("name", ""))
        flash("Branch renamed.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.branches"))


@bp.route("/departments/create", methods=["POST"])
@require_role("ADMIN")
def departments_create():
    admin_service.create_department(g.conn, request.form.get("name", ""))
    flash("Department added.", "success")
    return redirect(url_for("admin.branches"))


@bp.route("/departments/<department_id>/delete", methods=["POST"])
@require_role("ADMIN")
def departments_delete(department_id: str):
    try:
        admin_service.delete_department(g.conn, department_id)
        flash("Department deleted.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.branches"))


# --- Wastage Menu ---

@bp.route("/wastage-menu")
@require_role("ADMIN")
def wastage_menu():
    items_ = get_all_wastage_menu_items(g.conn)
    sections = [{"mealPeriod": mp, "items": [i for i in items_ if i["mealPeriod"] == mp and i["active"]]} for mp in MEAL_PERIODS]
    return render_template("admin/wastage_menu.html", sections=sections, meal_labels=MEAL_LABELS)


@bp.route("/wastage-menu/create", methods=["POST"])
@require_role("ADMIN")
def wastage_menu_create():
    try:
        create_wastage_menu_item(g.conn, request.form.get("mealPeriod", ""), request.form.get("name", ""),
                                  request.form.get("isPieceCounted") == "on")
        flash("Dish added.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.wastage_menu"))


@bp.route("/wastage-menu/<item_id>/delete", methods=["POST"])
@require_role("ADMIN")
def wastage_menu_delete(item_id: str):
    delete_wastage_menu_item(g.conn, item_id)
    flash("Dish removed.", "success")
    return redirect(url_for("admin.wastage_menu"))


# --- Users ---

@bp.route("/users")
@require_role("ADMIN")
def users():
    conn = g.conn
    user_rows = conn.execute(
        "SELECT u.*, b.name AS branchName FROM User u LEFT JOIN Branch b ON b.id = u.branchId "
        "WHERE u.active = 1 ORDER BY u.name ASC"
    ).fetchall()
    branch_rows = [dict(r) for r in conn.execute("SELECT id, name FROM Branch WHERE active = 1 ORDER BY name ASC")]
    return render_template("admin/users.html", users=[dict(r) for r in user_rows], branches=branch_rows, roles=ROLES)


@bp.route("/users/create", methods=["POST"])
@require_role("ADMIN")
def users_create():
    role = request.form.get("role", "STORE")
    admin_service.create_user(
        g.conn, request.form.get("name", ""), request.form.get("email", ""),
        request.form.get("password", ""), role, request.form.get("branchId") or None,
    )
    flash("User created.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<user_id>/deactivate", methods=["POST"])
@require_role("ADMIN")
def users_deactivate(user_id: str):
    admin_service.deactivate_user(g.conn, user_id)
    flash("User deactivated.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<user_id>/reset-password", methods=["POST"])
@require_role("ADMIN")
def users_reset_password(user_id: str):
    try:
        admin_service.reset_user_password(g.conn, user_id, request.form.get("newPassword", ""))
        flash("Password reset.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.users"))


# --- Status ---

@bp.route("/status")
@require_role("ADMIN")
def status():
    try:
        g.conn.execute("SELECT 1")
        db_ok, db_detail = True, "Connected"
    except Exception:
        db_ok, db_detail = False, "Could not connect"
    return render_template("admin/status.html", db_ok=db_ok, db_detail=db_detail)


# --- Branding ---

@bp.route("/branding")
@require_role("ADMIN")
def branding_page():
    branding = branding_service.get_branding(g.conn)
    return render_template(
        "admin/branding.html", branding=branding,
        theme_colors=branding_service.THEME_COLORS, theme_modes=branding_service.THEME_MODES,
        brand_sizes=branding_service.BRAND_SIZES, color_swatch=THEME_COLOR_SWATCH,
        color_label=THEME_COLOR_LABEL, mode_label=THEME_MODE_LABEL, size_label=BRAND_SIZE_LABEL,
    )


@bp.route("/branding/app-name", methods=["POST"])
@require_role("ADMIN")
def branding_app_name():
    try:
        branding_service.update_app_name(g.conn, request.form.get("appName", ""), request.form.get("tagline", ""))
        flash("Saved.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.branding_page"))


@bp.route("/branding/logo", methods=["POST"])
@require_role("ADMIN")
def branding_logo():
    from pathlib import Path
    file = request.files.get("logo")
    if not file or not file.filename:
        flash("No file provided.", "error")
        return redirect(url_for("admin.branding_page"))
    static_dir = Path(__file__).resolve().parent.parent / "static"
    branding_service.update_logo(g.conn, static_dir, file.filename, file.read())
    flash("Logo updated.", "success")
    return redirect(url_for("admin.branding_page"))


@bp.route("/branding/header-color", methods=["POST"])
@require_role("ADMIN")
def branding_header_color():
    try:
        branding_service.update_header_color(g.conn, request.form.get("headerColor", ""), request.form.get("reset") == "1")
        flash("Saved.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.branding_page"))


@bp.route("/branding/accent-color", methods=["POST"])
@require_role("ADMIN")
def branding_accent_color():
    try:
        branding_service.update_accent_color(g.conn, request.form.get("accentColor", ""), request.form.get("reset") == "1")
        flash("Saved.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.branding_page"))


@bp.route("/branding/theme", methods=["POST"])
@require_role("ADMIN")
def branding_theme():
    try:
        branding_service.update_theme(g.conn, request.form.get("themeColor", "navy"),
                                       request.form.get("themeMode", "system"), request.form.get("brandSize", "md"))
        flash("Theme saved.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.branding_page"))


# --- Legacy Excel Import (one-time, lowest priority) ---

@bp.route("/import")
@require_role("ADMIN")
def import_page():
    branches = [dict(r) for r in g.conn.execute("SELECT id, name FROM Branch WHERE active = 1 ORDER BY name ASC")]
    return render_template("admin/import.html", branches=branches)


@bp.route("/import/preview", methods=["POST"])
@require_role("ADMIN")
def import_preview():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a file first.", "error")
        return redirect(url_for("admin.import_page"))
    branches = [dict(r) for r in g.conn.execute("SELECT id, name FROM Branch WHERE active = 1 ORDER BY name ASC")]
    try:
        parsed = preview_excel_import(file.read())
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.import_page"))
    return render_template("admin/import_preview.html", parsed=parsed, branches=branches)


@bp.route("/import/commit", methods=["POST"])
@require_role("ADMIN")
def import_commit():
    file = request.files.get("file")
    branch_id = request.form.get("branchId", "")
    if not file or not file.filename or not branch_id:
        flash("Re-select the file and branch to confirm the import.", "error")
        return redirect(url_for("admin.import_page"))
    result = commit_excel_import(g.conn, file.read(), branch_id)
    flash(f"Imported {result['itemsCreated']} item(s), {result['purchasesCreated']} purchase(s), "
          f"{result['issuesCreated']} stock issue(s).", "success")
    return redirect(url_for("admin.import_page"))
