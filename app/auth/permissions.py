"""
Port of src/lib/auth/permissions.ts.

Single source of truth for route access. Deliberately a flat list, not a
generic permissions engine -- extend by adding rows, not by building more
machinery, until there's an actual need for finer-grained permissions.

VIEWER gets read access to everything MANAGER can see, but is blocked from
mutating routes -- checked separately via require_write (app/security.py).
"""
from __future__ import annotations

ROUTE_ACCESS: list[tuple[str, list[str]]] = [
    ("/admin", ["ADMIN"]),
    ("/dashboard", ["ADMIN", "MANAGER", "VIEWER"]),
    ("/tracker", ["ADMIN", "MANAGER", "STORE", "VIEWER"]),
    ("/wastage", ["ADMIN", "MANAGER", "STORE", "KITCHEN"]),
    ("/kitchen", ["ADMIN", "MANAGER", "KITCHEN"]),
    ("/requirements", ["ADMIN", "MANAGER", "VIEWER"]),
    ("/inventory", ["ADMIN", "MANAGER", "STORE", "VIEWER"]),
    ("/purchases", ["ADMIN", "MANAGER", "STORE"]),
    ("/issue", ["ADMIN", "MANAGER", "STORE"]),
    ("/reports", ["ADMIN", "MANAGER", "VIEWER"]),
]


def can_access_route(pathname: str, role: str) -> bool:
    for prefix, roles in ROUTE_ACCESS:
        if pathname.startswith(prefix):
            return role in roles
    return True  # routes not listed (e.g. /login) are open to any authenticated user


def can_write(role: str) -> bool:
    return role != "VIEWER"


def default_route_for_role(role: str) -> str:
    if role == "KITCHEN":
        return "/kitchen"
    if role == "STORE":
        return "/tracker"
    return "/dashboard"
