from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, session

from app.auth.permissions import default_route_for_role
from app.security import LegacyBcryptHash, verify_password

bp = Blueprint("login", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if g.user is not None:
            return redirect(default_route_for_role(g.user["role"]))
        callback_url = request.args.get("callbackUrl") or None
        return render_template("login.html", error=None, callback_url=callback_url)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    callback_url = request.form.get("callback_url") or None
    error = None

    if not username or not password:
        error = "Enter a username and password."
    else:
        row = g.conn.execute(
            "SELECT id, name, passwordHash, role, branchId, active FROM User WHERE email = ?", (username,)
        ).fetchone()
        if row is None or not row["active"]:
            error = "Invalid username or password."
        else:
            try:
                valid = verify_password(password, row["passwordHash"])
            except LegacyBcryptHash as e:
                error = str(e)
            else:
                if not valid:
                    error = "Invalid username or password."
                else:
                    session.clear()
                    session["user_id"] = row["id"]
                    # So the audit log's after_request hook records who just
                    # logged in, rather than the pre-login "no user" state
                    # that was already computed for this request.
                    g.user = {"id": row["id"], "name": row["name"], "email": username,
                              "role": row["role"], "branchId": row["branchId"]}
                    flash(f"Authenticated as {username} ({row['role']}).", "success")
                    dest = callback_url if callback_url and callback_url.startswith("/") else default_route_for_role(row["role"])
                    return redirect(dest)

    return render_template("login.html", error=error, callback_url=callback_url)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")
