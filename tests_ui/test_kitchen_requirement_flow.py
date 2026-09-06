"""Full Kitchen Requirement lifecycle against a live deployment:
Draft (hidden from Admin) -> Submit (visible) -> Approve -> Issue ->
Daily Tracker updates only at Issue. Plus the one-per-day restriction,
the Kitchen edit-with-reason flow, and Reject. Every test uses a unique
far-future date (TEST_DATE + a per-test offset) so runs never collide
with real data or with each other.
"""
from __future__ import annotations

import re

import pytest

from conftest import RUN_TAG, login_as, logout, require_role, unique_date

SOUTH_INDIAN = "SOUTH INDIAN"


def _requirement_id_from_url(url: str) -> str:
    m = re.search(r"requirementId=([0-9a-f]+)", url)
    assert m, f"no requirementId in {url}"
    return m.group(1)


def _pick_department_href(page, name: str) -> str:
    link = page.locator(f'a:has-text("{name}")').first
    href = link.get_attribute("href")
    assert href, f"no department link found for {name}"
    return href


def _fill_first_item_qty(page, qty: str):
    page.evaluate(
        """(qty) => {
            const input = document.querySelector('.js-qty-input');
            input.value = qty;
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }""",
        qty,
    )


def _tracker_row_cells(page, item_name: str) -> list[str]:
    """Playwright's locator.inner_text() on a <tr> can collapse/merge
    whitespace-only text nodes inconsistently across engines, making a
    plain \\n-split fragile (observed: fewer cells than expected). Read
    the actual <td> children's textContent directly instead, same
    approach already verified reliable during manual testing."""
    return page.evaluate(
        """(name) => {
            const rows = [...document.querySelectorAll('tbody tr')];
            const row = rows.find(r => r.textContent.includes(name));
            if (!row) return null;
            return [...row.children].map(td => td.textContent.trim());
        }""",
        item_name,
    )


def _submit_current_form(page, selector="form"):
    # page.evaluate() returns as soon as the JS call itself returns, which
    # can race ahead of the navigation requestSubmit() actually triggers --
    # wrapping in expect_navigation waits for the real navigation to land
    # before continuing, instead of racing page.content() against it.
    with page.expect_navigation():
        page.evaluate(f"document.querySelector('{selector}').requestSubmit()")
    page.wait_for_load_state("networkidle")


class TestDraftSubmitGating:
    def test_draft_hidden_from_admin_until_submitted(self, kitchen_page, admin_page, ui_base_url):
        date = unique_date(1)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
        href = _pick_department_href(kitchen_page, SOUTH_INDIAN)
        kitchen_page.goto(f"{ui_base_url}{href}")
        _fill_first_item_qty(kitchen_page, "4")
        _submit_current_form(kitchen_page, ".js-qty-draft")

        assert "Admin won't see this request until you click Submit" in kitchen_page.content()
        requirement_id = _requirement_id_from_url(kitchen_page.url)

        # Kitchen's own page shows it as an explicit Draft.
        kitchen_page.goto(f"{ui_base_url}/kitchen?date={date}")
        assert "Draft -- not submitted" in kitchen_page.content()
        assert requirement_id in kitchen_page.content()

        # Admin sees nothing for this date.
        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        assert requirement_id not in admin_page.content()
        assert "No kitchen requirements" in admin_page.content()

        # The Regular button is disabled while a draft/request exists for this date.
        kitchen_page.goto(f"{ui_base_url}/kitchen?date={date}")
        regular_btn = kitchen_page.locator('button:has-text("Request Regular Items")')
        assert regular_btn.count() == 1, "button should be a disabled <button>, not a clickable <a>, once one exists"
        assert regular_btn.is_disabled()

        # Submit -- now Admin must see it.
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}&requirementId={requirement_id}")
        _submit_current_form(kitchen_page, 'form[action*="/submit"]')

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        assert requirement_id in admin_page.content()
        assert "Pending Review" in admin_page.content()

    def test_second_regular_request_same_day_resumes_existing_draft(self, kitchen_page, ui_base_url):
        date = unique_date(2)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
        href = _pick_department_href(kitchen_page, SOUTH_INDIAN)
        kitchen_page.goto(f"{ui_base_url}{href}")
        _fill_first_item_qty(kitchen_page, "2")
        _submit_current_form(kitchen_page, ".js-qty-draft")
        first_id = _requirement_id_from_url(kitchen_page.url)

        # Clicking "Request Regular Items" again for the same date must
        # resume the SAME draft, never create a second one.
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
        second_id = _requirement_id_from_url(kitchen_page.url)
        assert first_id == second_id


class TestApproveIssueTrackerGating:
    def test_tracker_only_updates_at_issue_not_at_approve(self, kitchen_page, admin_page, ui_base_url):
        date = unique_date(3)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
        href = _pick_department_href(kitchen_page, SOUTH_INDIAN)
        kitchen_page.goto(f"{ui_base_url}{href}")

        # Use the item name visible in this department's list so we can
        # find the same row again on Daily Tracker afterward.
        item_name = kitchen_page.locator(".js-search-row span").first.inner_text()
        _fill_first_item_qty(kitchen_page, "3")
        _submit_current_form(kitchen_page, ".js-qty-draft")
        requirement_id = _requirement_id_from_url(kitchen_page.url)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}&requirementId={requirement_id}")
        _submit_current_form(kitchen_page, 'form[action*="/submit"]')

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        admin_page.locator('button:has-text("Approve")').first.click()
        admin_page.wait_for_load_state("networkidle")

        # Approved-not-issued: Daily Tracker's Kitchen Req./Issued columns
        # for this item must both still read 0.
        admin_page.goto(f"{ui_base_url}/tracker?date={date}")
        cells = _tracker_row_cells(admin_page, item_name)
        assert cells is not None, f"row for {item_name!r} not found on tracker"
        assert cells[4] == "0", f"Kitchen Req. should be 0 before Issue, row: {cells}"
        assert cells[5] == "0", f"Issued should be 0 before Issue, row: {cells}"

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        admin_page.locator('button:has-text("Issue")').first.click()
        admin_page.wait_for_load_state("networkidle")

        admin_page.goto(f"{ui_base_url}/tracker?date={date}")
        cells = _tracker_row_cells(admin_page, item_name)
        assert cells is not None, f"row for {item_name!r} not found on tracker"
        assert cells[4] == "3", f"Kitchen Req. should be 3 after Issue, row: {cells}"
        assert cells[5] == "3", f"Issued should be 3 after Issue, row: {cells}"

    def test_approve_requires_admin_role_not_kitchen(self, kitchen_page, ui_base_url):
        # KITCHEN has no access to /requirements at all.
        resp = kitchen_page.goto(f"{ui_base_url}/requirements")
        assert resp.status < 500
        assert "/requirements" not in kitchen_page.url


class TestRejectFlow:
    def test_reject_removes_pending_request(self, kitchen_page, admin_page, ui_base_url):
        date = unique_date(4)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
        href = _pick_department_href(kitchen_page, SOUTH_INDIAN)
        kitchen_page.goto(f"{ui_base_url}{href}")
        _fill_first_item_qty(kitchen_page, "1")
        _submit_current_form(kitchen_page, ".js-qty-draft")
        requirement_id = _requirement_id_from_url(kitchen_page.url)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}&requirementId={requirement_id}")
        _submit_current_form(kitchen_page, 'form[action*="/submit"]')

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        admin_page.fill("textarea", "Duplicate of another request -- UI regression test")
        admin_page.locator('button:has-text("Reject")').first.click()
        admin_page.wait_for_load_state("networkidle")

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        assert requirement_id not in admin_page.content()
        assert "No kitchen requirements" in admin_page.content()

        # Rejected -> Kitchen can start a brand new Regular request for
        # the same date again (it's not permanently blocked).
        kitchen_page.goto(f"{ui_base_url}/kitchen?date={date}")
        regular_btn = kitchen_page.locator('button:has-text("Request Regular Items")')
        assert regular_btn.count() == 0, "button should be an active <a> again after reject freed up the date"


class TestKitchenEditWithReason:
    def test_edit_after_approval_requires_reason_and_reverts_to_pending(self, kitchen_page, admin_page, ui_base_url):
        date = unique_date(5)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
        href = _pick_department_href(kitchen_page, SOUTH_INDIAN)
        kitchen_page.goto(f"{ui_base_url}{href}")
        item_name = kitchen_page.locator(".js-search-row span").first.inner_text()
        _fill_first_item_qty(kitchen_page, "4")
        _submit_current_form(kitchen_page, ".js-qty-draft")
        requirement_id = _requirement_id_from_url(kitchen_page.url)
        kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}&requirementId={requirement_id}")
        _submit_current_form(kitchen_page, 'form[action*="/submit"]')

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        admin_page.locator('button:has-text("Approve")').first.click()
        admin_page.wait_for_load_state("networkidle")

        kitchen_page.goto(f"{ui_base_url}/kitchen/review/{requirement_id}")
        assert "Request an edit" in kitchen_page.content()
        kitchen_page.click('button:has-text("Request an edit")')
        kitchen_page.fill('dialog textarea[name="reason"]', f"UI regression test {RUN_TAG}")
        kitchen_page.click('dialog button:has-text("Continue")')
        kitchen_page.wait_for_load_state("networkidle")

        assert "Edit Request" in kitchen_page.content()
        kitchen_page.fill(".js-edit-qty", "2")
        # The per-item reason field should reveal itself once qty changed.
        reason_field = kitchen_page.locator(".js-edit-reason-field input")
        assert reason_field.is_visible()
        reason_field.fill("Store only had 2kg in stock -- UI regression test")
        _submit_current_form(kitchen_page, "#edit-form")

        assert "pending admin approval again" in kitchen_page.content()

        admin_page.goto(f"{ui_base_url}/requirements?date={date}")
        assert requirement_id in admin_page.content()
        assert "Pending Review" in admin_page.content()
