"""End-to-end nav + route-access regression suite.

Exists specifically because of a real incident: a removed feature
(Workstation Photos) kept appearing as a "More" nav dropdown in
production long after the code was deleted, because the deploy script
(`cp -R`, since fixed to `rsync --delete`) never removed the old files
from the server. This suite can't catch a broken deploy script, but it
locks down what the CODE ITSELF renders and permits for every role, so
a future "removed feature still visible" bug would have to be a genuine
code regression, not something that slips through some other layer.

Deliberately data-driven from app.auth.permissions.ROUTE_ACCESS and
app.__init__._ALL_NAV_LINKS themselves (not a hand-copied duplicate
list) -- so this suite can't silently drift out of sync with the real
rules the way a hand-maintained expected-links list would.
"""
from __future__ import annotations

import pytest

from app.auth.permissions import ROUTE_ACCESS, can_access_route, default_route_for_role
from tests.conftest import login, make_user

ALL_ROLES = ("ADMIN", "MANAGER", "STORE", "KITCHEN", "VIEWER", "DEPARTMENT_LEAD")

# GET-only, no-arg routes safe to hit directly for a plain visibility check.
SIMPLE_GET_ROUTES = (
    "/dashboard", "/inventory", "/tracker", "/wastage", "/kitchen",
    "/intent", "/recipe", "/requirements", "/issue", "/purchases", "/admin",
)


def _client_as(full_app, full_db_conn, branch_id, role: str):
    """A fresh test client (its own cookie jar) logged in as a brand-new
    user of the given role -- always uses a NEW client per call so
    testing multiple roles in one test never trips over "already logged
    in" redirecting /login away before the CSRF token can be scraped."""
    client = full_app.test_client()
    user_id, username, password = make_user(full_db_conn, role, branch_id)
    resp = login(client, username, password)
    assert resp.status_code == 302, f"login failed for role {role}: {resp.get_data(as_text=True)[:300]}"
    return client


class TestNoStaleFeatureAnywhere:
    """The exact regression class from the incident: assert a removed
    feature can never resurface in the nav or be reachable by URL, for
    ANY role -- not just the one role that happened to be tested live."""

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_workstation_not_in_nav_or_page_for_any_role(self, full_app, full_db_conn, branch_id, role):
        client = _client_as(full_app, full_db_conn, branch_id, role)
        resp = client.get(default_route_for_role(role))
        body = resp.get_data(as_text=True).lower()
        assert "workstation" not in body, f"{role} sees 'workstation' on their landing page"

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_workstation_route_unreachable_for_any_role(self, full_app, full_db_conn, branch_id, role):
        client = _client_as(full_app, full_db_conn, branch_id, role)
        resp = client.get("/workstation")
        assert resp.status_code in (302, 404), f"{role} can still reach /workstation ({resp.status_code})"
        if resp.status_code == 302:
            assert "/workstation" not in resp.headers["Location"]

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_no_more_dropdown_leftover_for_any_role(self, full_client, full_db_conn, branch_id, role):
        """Structural check, not a hand-copied list: every nav link visible
        to this role must be covered by a slot in _DESKTOP_SLOTS. If a
        future addition to _ALL_NAV_LINKS forgets to add a matching slot,
        this fails immediately instead of silently growing a "More" group
        nobody notices until a user reports it."""
        from app import _ALL_NAV_LINKS, _DESKTOP_SLOTS
        slotted = {href for slot in _DESKTOP_SLOTS for href in (slot[1:2] if slot[0] == "link" else slot[2])}
        visible = {link["href"] for link in _ALL_NAV_LINKS if role in link["roles"]}
        leftover = visible - slotted
        assert not leftover, f"{role} would see a 'More' dropdown containing: {leftover}"


class TestRouteAccessMatchesPermissionsTable:
    """For every (route prefix, role) pair, confirm the live HTTP response
    matches what ROUTE_ACCESS says it should be -- catches drift between
    the permissions table and what a route's own code actually enforces."""

    @pytest.mark.parametrize("prefix,allowed_roles", ROUTE_ACCESS)
    def test_every_role_matches_route_access_table(self, full_app, full_db_conn, branch_id, prefix, allowed_roles):
        if prefix not in SIMPLE_GET_ROUTES:
            pytest.skip(f"{prefix} needs args to GET meaningfully, covered by its own feature-specific test file")
        for role in ALL_ROLES:
            client = _client_as(full_app, full_db_conn, branch_id, role)
            resp = client.get(prefix)
            should_allow = can_access_route(prefix, role)
            if should_allow:
                assert resp.status_code == 200, (
                    f"{role} should reach {prefix} per ROUTE_ACCESS but got {resp.status_code}"
                )
            else:
                assert resp.status_code == 302, (
                    f"{role} should be BLOCKED from {prefix} per ROUTE_ACCESS but got {resp.status_code}"
                )
                assert not resp.headers["Location"].rstrip("/").endswith(prefix), (
                    f"{role} was redirected right back to the blocked page {prefix} -- bounce target is wrong"
                )


class TestDefaultLandingPageIsReachable:
    """Every role's default_route_for_role() target must itself be a page
    that role can actually access -- otherwise login redirects them into
    an immediate second bounce (or worse, a loop)."""

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_default_route_is_accessible_to_its_own_role(self, full_app, full_db_conn, branch_id, role):
        client = _client_as(full_app, full_db_conn, branch_id, role)
        target = default_route_for_role(role)
        resp = client.get(target)
        assert resp.status_code == 200, (
            f"{role}'s default landing page {target} isn't accessible to {role} itself ({resp.status_code})"
        )


class TestUnauthenticatedAccess:
    def test_every_protected_route_redirects_when_logged_out(self, full_client):
        for prefix in SIMPLE_GET_ROUTES:
            resp = full_client.get(prefix)
            assert resp.status_code == 302, f"{prefix} accessible without login"
            assert "/login" in resp.headers["Location"]
