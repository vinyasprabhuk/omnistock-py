"""Broad smoke coverage: every remaining nav tab not already covered by
a deep feature test (Dashboard, Master Inventory, Recipe, Daily
Tracker) renders without a server error for a role that can access it,
and 500s are treated as failures everywhere -- catches template/JS
regressions in pages that don't have dedicated business-logic tests."""
from __future__ import annotations


def _assert_clean_page(page, resp):
    assert resp.status < 500, f"{page.url} returned {resp.status}"
    content = page.content()
    assert "Traceback" not in content
    assert "Internal Server Error" not in content


def test_dashboard_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/dashboard")
    _assert_clean_page(admin_page, resp)
    assert "Dashboard" in admin_page.content()


def test_master_inventory_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/inventory")
    _assert_clean_page(admin_page, resp)


def test_daily_tracker_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/tracker")
    _assert_clean_page(admin_page, resp)


def test_daily_tracker_export_link_present(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/tracker")
    assert admin_page.locator('a[href*="/api/export/tracker"]').count() >= 1


def test_recipe_page_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/recipe")
    _assert_clean_page(admin_page, resp)


def test_admin_hub_loads(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/admin")
    _assert_clean_page(admin_page, resp)


def test_audit_log_loads_and_has_no_column_error(admin_page, ui_base_url):
    """Direct regression check for the real bug hit tonight: audit.db
    missing the AuditEvent table produces exactly this page 500ing."""
    resp = admin_page.goto(f"{ui_base_url}/admin/audit-log")
    _assert_clean_page(admin_page, resp)
    assert "no such table" not in admin_page.content()


def test_kitchen_page_loads_for_kitchen_role(kitchen_page, ui_base_url):
    resp = kitchen_page.goto(f"{ui_base_url}/kitchen")
    _assert_clean_page(kitchen_page, resp)
    assert "What do you need" in kitchen_page.content()


def test_wastage_page_loads_for_kitchen_role(kitchen_page, ui_base_url):
    resp = kitchen_page.goto(f"{ui_base_url}/wastage")
    _assert_clean_page(kitchen_page, resp)


def test_purchases_page_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/purchases")
    _assert_clean_page(admin_page, resp)


def test_intent_page_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/intent")
    _assert_clean_page(admin_page, resp)


def test_requirements_page_loads_for_admin(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/requirements")
    _assert_clean_page(admin_page, resp)


def test_unknown_route_does_not_500(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/this-route-does-not-exist-ui-test")
    assert resp.status in (404, 302), f"expected a clean 404/redirect, got {resp.status}"
    assert resp.status < 500
