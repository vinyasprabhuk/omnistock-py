"""
Password hashing, CSRF protection, and the @login_required / @require_role
decorators used across every view.
"""
from __future__ import annotations

import functools
import secrets

from flask import abort, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth.permissions import default_route_for_role


# --- Passwords ---

def hash_password(plain: str) -> str:
    """PBKDF2-SHA256 via Werkzeug -- pure Python, no compiled dependency."""
    return generate_password_hash(plain)


class LegacyBcryptHash(Exception):
    """Raised when a user's stored hash is a leftover bcrypt hash from the
    Next.js app that hasn't been migrated yet (see tools/migrate_admin_password.py)."""


def verify_password(plain: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$2"):
        # bcrypt hash (bcryptjs from the old Next.js app) -- this port
        # deliberately doesn't ship a bcrypt-compatible verifier (it would be
        # a compiled dependency, exactly what this rewrite exists to avoid).
        raise LegacyBcryptHash(
            "This account still uses the old password format and must be "
            "reset by an admin (see tools/migrate_admin_password.py)."
        )
    return check_password_hash(stored_hash, plain)


# --- CSRF ---

def get_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


def validate_csrf() -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    submitted = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
    expected = session.get("_csrf_token")
    if not expected or not submitted or not secrets.compare_digest(submitted, expected):
        abort(403, description="Invalid or missing CSRF token")


# --- Decorators ---

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login.login", callbackUrl=request.path))
        return view(*args, **kwargs)
    return wrapped


def require_role(*allowed_roles: str):
    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in allowed_roles:
                return redirect(default_route_for_role(g.user["role"]))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def require_write(view):
    """Blocks VIEWER (and any unauthenticated user) from mutating routes."""
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] == "VIEWER":
            abort(403, description="Read-only access")
        return view(*args, **kwargs)
    return wrapped
