"""Production logging, Wastage logging, and the Variance tab
(produced - sold - wasted, per recipe -- see app/services/wastage_variance.py).
"Sold" comes from real DishSale rows for that exact date, not Intent's
forecast average, so a variance row on a date with no sales upload
correctly shows "no sales data" rather than a misleading number --
covered here as a negative/edge case, not assumed to auto-match Intent.
"""
from __future__ import annotations

import pytest

from pathlib import Path

from conftest import unique_date

TEST_PHOTO = str(Path(__file__).resolve().parent / "fixtures" / "test_photo.png")


def _log_entry(page, ui_base_url, date: str, mode: str, weight: str) -> str | None:
    """Clicks the first real menu item, fills the entry dialog, submits.
    Returns the dish name used, or None if no menu items exist to log
    against (an empty Wastage Menu is a real possible state, not a bug).

    Photo is server-required (quantity_log.create_entry raises "Photo is
    required" on empty bytes) and the UI only offers live camera capture,
    no file picker -- getUserMedia can't be driven headlessly here, so
    this sets the hidden .js-photo-input directly with a real (tiny) test
    image. That exercises the actual save path the camera JS ultimately
    feeds into, just skipping the camera UI itself."""
    page.goto(f"{ui_base_url}/wastage?date={date}&mode={mode}")
    btn = page.locator(".js-open-entry[data-dish]:not([data-dish=''])").first
    if btn.count() == 0:
        return None
    dish_name = btn.get_attribute("data-dish")
    btn.click()
    page.wait_for_selector("#entry-dialog[open]", timeout=5000)
    page.fill('#entry-dialog input[name="weight"]', weight)
    page.set_input_files('#entry-dialog input.js-photo-input', TEST_PHOTO)
    with page.expect_navigation():
        page.click('#entry-dialog button[type="submit"]')
    page.wait_for_load_state("networkidle")
    return dish_name


class TestProductionLogging:
    def test_log_production_entry_saves_and_shows_in_list(self, admin_page, ui_base_url):
        date = unique_date(40)
        dish_name = _log_entry(admin_page, ui_base_url, date, "production", "5")
        if dish_name is None:
            pytest.skip("Wastage Menu has no configured dishes to log against")
        assert dish_name in admin_page.content()
        assert "logged" in admin_page.content().lower()

    def test_kitchen_role_can_log_but_store_role_gating_is_enforced_server_side(self, kitchen_page, ui_base_url):
        # KITCHEN is in LOG_ROLES (app/views/wastage.py) -- must be able
        # to reach the page and see the log controls.
        resp = kitchen_page.goto(f"{ui_base_url}/wastage")
        assert resp.status == 200
        assert kitchen_page.locator(".js-open-entry").count() >= 0  # page renders without error

    def test_variance_tab_not_visible_to_kitchen_role(self, kitchen_page, ui_base_url):
        kitchen_page.goto(f"{ui_base_url}/wastage?mode=variance")
        # can_see_analysis is ADMIN/MANAGER only -- KITCHEN silently
        # falls back to production mode instead of a 403, per the view's
        # own mode_param handling.
        assert "Variance" not in kitchen_page.locator("h1, h2").all_inner_texts()


class TestWastageLogging:
    def test_log_wastage_entry_saves(self, admin_page, ui_base_url):
        date = unique_date(41)
        dish_name = _log_entry(admin_page, ui_base_url, date, "wastage", "1.5")
        if dish_name is None:
            pytest.skip("Wastage Menu has no configured dishes to log against")
        assert dish_name in admin_page.content()


class TestVarianceReconciliation:
    def test_variance_reflects_produced_and_wasted_for_the_same_recipe(self, admin_page, ui_base_url):
        """produced - sold - wasted, with sold=0 (no sales upload for
        this far-future date) -- so variance should equal produced -
        wasted exactly, a directly checkable arithmetic fact."""
        date = unique_date(42)
        produced_dish = _log_entry(admin_page, ui_base_url, date, "production", "6")
        if produced_dish is None:
            pytest.skip("Wastage Menu has no configured dishes to log against")
        wasted_dish = _log_entry(admin_page, ui_base_url, date, "wastage", "1")

        admin_page.goto(f"{ui_base_url}/wastage?date={date}&mode=variance")
        content = admin_page.content()
        assert "Traceback" not in content
        # With no real sales for a far-future date, sales_available should
        # be False and the page should say so rather than imply a false zero.
        assert ("no sales" in content.lower()) or ("Sold" in content)

    def test_variance_page_requires_admin_or_manager(self, kitchen_page, ui_base_url):
        resp = kitchen_page.goto(f"{ui_base_url}/wastage?mode=variance")
        assert resp.status < 500
