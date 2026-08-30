from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.page_department import VIEW_ALL_ROLES, list_departments_for_admin, page_resolve_department
from app.security import require_write
from app.services import workstation

bp = Blueprint("workstation", __name__)


@bp.route("/workstation")
def index():
    conn = g.conn
    can_view_all = g.user["role"] in VIEW_ALL_ROLES
    can_log = g.user["role"] == "DEPARTMENT_LEAD"
    dept_param = request.args.get("departmentId")

    try:
        department = page_resolve_department(conn, g.user, dept_param)
    except ValueError as e:
        abort(400, description=str(e))

    departments = list_departments_for_admin(conn) if can_view_all else []
    entries = workstation.get_for_department(conn, department["departmentId"])

    return render_template(
        "workstation/index.html", department=department, can_view_all=can_view_all,
        can_log=can_log, departments=departments, entries=entries,
    )


@bp.route("/workstation/capture", methods=["POST"])
@require_write
def capture():
    if g.user["role"] != "DEPARTMENT_LEAD":
        abort(403, description="Only Department Leads can capture workstation photos")

    conn = g.conn
    department_id = g.user.get("departmentId")
    branch_id = g.user.get("branchId")
    photo = request.files.get("photo")

    try:
        if not department_id:
            raise ValueError("Your account has no department assigned -- contact an admin")
        if not branch_id:
            raise ValueError("Your account has no branch assigned -- contact an admin")
        photo_bytes = photo.read() if photo and photo.filename else b""
        fn = photo.filename if photo else ""
        mime = photo.mimetype if photo else None
        workstation.create_photo(conn, g.user["id"], branch_id, department_id, photo_bytes, fn, mime)
        flash("Photo captured.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("workstation.index"))
