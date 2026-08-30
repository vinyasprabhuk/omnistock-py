from __future__ import annotations

from flask import Flask, g, redirect, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth.permissions import can_access_route, can_write, default_route_for_role
from app.db import get_connection
from app.security import get_csrf_token, validate_csrf

# Paths open to anyone, matching src/proxy.ts's PUBLIC_PATHS. manifest.json/
# sw.js must be public too -- the browser fetches these to decide if the site
# is installable, before any login has happened.
PUBLIC_PATHS = ("/login", "/branding", "/static", "/manifest.json", "/sw.js")


def create_app(config_object: str = "config.Config") -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    # Passenger/Apache terminate TLS and proxy to this app over plain HTTP,
    # setting X-Forwarded-Proto/Host. Without this, request.is_secure and
    # url_for(_external=True) would think every request is plain HTTP even
    # in production, which silently breaks SESSION_COOKIE_SECURE and any
    # absolute-URL generation -- another local-vs-prod gap worth closing up
    # front rather than discovering it live (matches ProxyFix's documented
    # use case exactly).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from app.views.login import bp as login_bp
    from app.views.files import bp as files_bp
    from app.views.tracker import bp as tracker_bp
    from app.views.inventory import bp as inventory_bp
    from app.views.requirements import bp as requirements_bp
    from app.views.export import bp as export_bp
    from app.views.dashboard import bp as dashboard_bp
    from app.views.purchases import bp as purchases_bp
    from app.views.issue import bp as issue_bp
    from app.views.kitchen import bp as kitchen_bp
    from app.views.wastage import bp as wastage_bp
    from app.views.admin import bp as admin_bp
    from app.views.pwa import bp as pwa_bp
    from app.views.intent import bp as intent_bp
    from app.views.recipe import bp as recipe_bp

    app.register_blueprint(login_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(pwa_bp)
    app.register_blueprint(tracker_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(requirements_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(issue_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(kitchen_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(wastage_bp)
    app.register_blueprint(intent_bp)
    app.register_blueprint(recipe_bp)

    from app.services.color import is_light_color
    from app.formatting import fmt, money, money_grouped, pct
    from app.dates import shift_date_key, today_key
    app.jinja_env.filters["is_light_color"] = is_light_color
    app.jinja_env.filters["fmt"] = fmt
    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["money_grouped"] = money_grouped
    app.jinja_env.filters["pct"] = pct
    app.jinja_env.filters["shift_date"] = shift_date_key
    app.jinja_env.globals["today_key"] = today_key

    @app.before_request
    def load_user_and_enforce_rbac():
        g.conn = get_connection()

        user_id = session.get("user_id")
        g.user = None
        if user_id:
            row = g.conn.execute(
                "SELECT id, name, email, role, branchId, active FROM User WHERE id = ?", (user_id,)
            ).fetchone()
            if row and row["active"]:
                g.user = {
                    "id": row["id"], "name": row["name"], "email": row["email"],
                    "role": row["role"], "branchId": row["branchId"],
                }
            else:
                # Account deactivated/deleted since login -- drop the stale session.
                session.clear()

        path = request.path

        if any(path == p or path.startswith(p + "/") or path == p for p in PUBLIC_PATHS) or path.startswith("/static/"):
            return None

        if g.user is None:
            return redirect(url_for("login.login", callbackUrl=path))

        role = g.user["role"]

        if path == "/":
            return redirect(default_route_for_role(role))

        if not can_access_route(path, role):
            return redirect(default_route_for_role(role))

        if request.method != "GET" and not can_write(role):
            from flask import jsonify
            return jsonify({"error": "Read-only access"}), 403

        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            validate_csrf()

        return None

    @app.after_request
    def log_audit_event(response):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return response
        if request.path.startswith("/static/"):
            return response
        try:
            from app.services.audit_log import write_event
            write_event(
                app.config["AUDIT_DB_PATH"],
                user=getattr(g, "user", None),
                method=request.method,
                path=request.path,
                endpoint=request.endpoint,
                status_code=response.status_code,
                form=request.form.to_dict() if request.form else None,
                view_args=request.view_args,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            )
        except Exception:
            # Audit logging must never break the actual request -- a
            # missing/locked audit.db is a problem to notice and fix, not
            # a reason to 500 every write in the app.
            app.logger.exception("Failed to write audit event")
        return response

    @app.teardown_request
    def close_db(exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def inject_globals():
        from app.services.branding import get_branding
        from app.services.kitchen_requirement import get_pending_requirements
        branding = get_branding(g.conn) if getattr(g, "conn", None) else None
        pending_count = len(get_pending_requirements(g.conn, g.user)) if getattr(g, "conn", None) else 0
        return {
            "branding": branding,
            "current_user": getattr(g, "user", None),
            "csrf_token": get_csrf_token,
            "nav_links": _nav_links(getattr(g, "user", None)),
            "nav_groups": _nav_groups(getattr(g, "user", None)),
            "pending_requirement_count": pending_count,
        }

    return app


_ALL_NAV_LINKS = [
    {"href": "/dashboard", "label": "Dashboard", "roles": ["ADMIN", "MANAGER", "VIEWER"]},
    {"href": "/inventory", "label": "Master Inventory", "roles": ["ADMIN", "MANAGER", "STORE", "VIEWER"]},
    {"href": "/kitchen", "label": "Kitchen Upload", "roles": ["ADMIN", "MANAGER", "KITCHEN"]},
    {"href": "/intent", "label": "Intent", "roles": ["ADMIN"]},
    {"href": "/recipe", "label": "Recipe", "roles": ["ADMIN"]},
    {"href": "/requirements", "label": "Requirements", "roles": ["ADMIN", "MANAGER", "VIEWER"]},
    {"href": "/tracker", "label": "Daily Tracker", "roles": ["ADMIN", "MANAGER", "STORE", "VIEWER"]},
    {"href": "/issue", "label": "Stock Issue", "roles": ["ADMIN", "MANAGER", "STORE"]},
    {"href": "/wastage", "label": "Wastage", "roles": ["ADMIN", "MANAGER", "KITCHEN"]},
    {"href": "/purchases", "label": "Purchases", "roles": ["ADMIN", "MANAGER", "STORE"]},
    {"href": "/admin", "label": "Admin", "roles": ["ADMIN"]},
]

# Desktop nav order: items people use many times a day sit directly in the
# bar (single click), with the rest tucked into two labeled dropdowns
# instead of hiding everything behind a hamburger -- that's reserved for
# narrow screens (see base.html), where there's no room for a horizontal
# bar at all. Slots not covered here fall back into a trailing "More"
# group so a future addition never silently disappears from the nav.
_DESKTOP_SLOTS = [
    ("link", "/dashboard"),
    ("link", "/inventory"),
    ("link", "/tracker"),
    ("group", "Operations", ["/purchases", "/issue", "/wastage"]),
    ("group", "Planning", ["/intent", "/recipe", "/kitchen", "/requirements"]),
    ("link", "/admin"),
]


def _nav_links(user: dict | None) -> list[dict]:
    if user is None:
        return []
    return [link for link in _ALL_NAV_LINKS if user["role"] in link["roles"]]


def _nav_groups(user: dict | None) -> list[dict]:
    """Desktop nav structure: a mix of direct links and labeled dropdown
    groups, built from the same role-filtered link set as the mobile
    hamburger so the two never drift out of sync on what's visible."""
    visible = _nav_links(user)
    by_href = {link["href"]: link for link in visible}
    slotted_hrefs = {href for slot in _DESKTOP_SLOTS for href in (slot[1:2] if slot[0] == "link" else slot[2])}

    structure: list[dict] = []
    for slot in _DESKTOP_SLOTS:
        if slot[0] == "link":
            href = slot[1]
            if href in by_href:
                structure.append({"type": "link", **by_href[href]})
        else:
            _, label, hrefs = slot
            items = [by_href[href] for href in hrefs if href in by_href]
            if items:
                structure.append({"type": "group", "label": label, "items": items})
    leftover = [link for link in visible if link["href"] not in slotted_hrefs]
    if leftover:
        structure.append({"type": "group", "label": "More", "items": leftover})
    return structure
