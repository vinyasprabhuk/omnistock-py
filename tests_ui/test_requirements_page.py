"""Requirements page specifics not already covered by the full lifecycle
test: the transaction id display, and the "Needs action on other dates"
banner when a request exists for a date other than the one selected."""
from __future__ import annotations

import re

from conftest import unique_date


def _requirement_id_from_url(url: str) -> str:
    m = re.search(r"requirementId=([0-9a-f]+)", url)
    assert m, f"no requirementId in {url}"
    return m.group(1)


def test_transaction_id_shown_on_requirements_and_kitchen_pages(kitchen_page, admin_page, ui_base_url):
    date = unique_date(50)
    kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={date}")
    href = kitchen_page.locator('a:has-text("SOUTH INDIAN")').first.get_attribute("href")
    kitchen_page.goto(f"{ui_base_url}{href}")
    kitchen_page.evaluate(
        """() => {
            const input = document.querySelector('.js-qty-input');
            input.value = '1';
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }"""
    )
    with kitchen_page.expect_navigation():
        kitchen_page.evaluate("document.querySelector('.js-qty-draft').requestSubmit()")
    requirement_id = _requirement_id_from_url(kitchen_page.url)

    with kitchen_page.expect_navigation():
        kitchen_page.evaluate('document.querySelector(\'form[action*="/submit"]\').requestSubmit()')

    # Txn id must appear verbatim on the Kitchen Upload page...
    kitchen_page.goto(f"{ui_base_url}/kitchen?date={date}")
    assert requirement_id in kitchen_page.content()

    # ...and on the Requirements page's Pending Review section...
    admin_page.goto(f"{ui_base_url}/requirements?date={date}")
    assert requirement_id in admin_page.content()

    # ...and on the Kitchen Requirement Review page itself.
    admin_page.goto(f"{ui_base_url}/kitchen/review/{requirement_id}")
    assert requirement_id in admin_page.content()


def test_needs_action_banner_points_at_other_dates_with_pending_work(kitchen_page, admin_page, ui_base_url):
    today_view_date = unique_date(60)
    other_date = unique_date(61)

    kitchen_page.goto(f"{ui_base_url}/kitchen/request?type=regular&date={other_date}")
    href = kitchen_page.locator('a:has-text("SOUTH INDIAN")').first.get_attribute("href")
    kitchen_page.goto(f"{ui_base_url}{href}")
    kitchen_page.evaluate(
        """() => {
            const input = document.querySelector('.js-qty-input');
            input.value = '1';
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }"""
    )
    with kitchen_page.expect_navigation():
        kitchen_page.evaluate("document.querySelector('.js-qty-draft').requestSubmit()")
    with kitchen_page.expect_navigation():
        kitchen_page.evaluate('document.querySelector(\'form[action*="/submit"]\').requestSubmit()')

    # Viewing an UNRELATED date must surface a banner pointing at other_date.
    admin_page.goto(f"{ui_base_url}/requirements?date={today_view_date}")
    assert "Needs action on other dates" in admin_page.content()
    assert other_date in admin_page.content()

    link = admin_page.locator(f'a[href*="date={other_date}"]').first
    assert link.count() == 1
    with admin_page.expect_navigation():
        link.click()
    assert other_date in admin_page.url
    assert "Pending Review" in admin_page.content()


def test_requirements_page_shows_clean_empty_state(admin_page, ui_base_url):
    far_empty_date = unique_date(999)
    admin_page.goto(f"{ui_base_url}/requirements?date={far_empty_date}")
    content = admin_page.content()
    assert "Traceback" not in content
    assert "No kitchen requirements" in content
