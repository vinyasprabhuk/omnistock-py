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

    @app.teardown_request
    def close_db(exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def inject_globals():
        from app.services.branding import get_branding
        branding = get_branding(g.conn) if getattr(g, "conn", None) else None
        return {
            "branding": branding,
            "current_user": getattr(g, "user", None),
            "csrf_token": get_csrf_token,
            "nav_links": _nav_links(getattr(g, "user", None)),
        }

    return app


def _nav_links(user: dict | None) -> list[dict]:
    if user is None:
        return []
    all_links = [
        {"href": "/dashboard", "label": "Dashboard", "roles": ["ADMIN", "MANAGER", "VIEWER"]},
        {"href": "/inventory", "label": "Master Inventory", "roles": ["ADMIN", "MANAGER", "STORE", "VIEWER"]},
        {"href": "/kitchen", "label": "Kitchen Upload", "roles": ["ADMIN", "MANAGER", "KITCHEN"]},
        {"href": "/intent", "label": "Intent", "roles": ["ADMIN"]},
        {"href": "/recipe", "label": "Recipe", "roles": ["ADMIN"]},
        {"href": "/requirements", "label": "Requirements", "roles": ["ADMIN", "MANAGER", "VIEWER"]},
        {"href": "/tracker", "label": "Daily Tracker", "roles": ["ADMIN", "MANAGER", "STORE", "VIEWER"]},
        {"href": "/issue", "label": "Stock Issue", "roles": ["ADMIN", "MANAGER", "STORE"]},
        {"href": "/wastage", "label": "Wastage", "roles": ["ADMIN", "MANAGER", "STORE", "KITCHEN"]},
        {"href": "/purchases", "label": "Purchases", "roles": ["ADMIN", "MANAGER", "STORE"]},
        {"href": "/admin", "label": "Admin", "roles": ["ADMIN"]},
    ]
    return [link for link in all_links if user["role"] in link["roles"]]
