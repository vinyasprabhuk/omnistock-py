"""Stock Issue manual entry -- positive and negative."""
from __future__ import annotations

from conftest import unique_date


def test_create_issue_saves_and_shows_on_tracker(admin_page, ui_base_url):
    date = unique_date(20)
    admin_page.goto(f"{ui_base_url}/issue")
    item_select = admin_page.locator('#issue-lines select[name="itemId"]') \
        if admin_page.locator('#issue-lines select[name="itemId"]').count() \
        else admin_page.locator('select[name="itemId"]').first
    item_name_selected = item_select.evaluate(
        "el => el.options[1] ? el.options[1].textContent : null"
    )
    admin_page.fill('input[name="date"]', date)
    admin_page.fill('input[name="departmentName"]', "UI Test Dept")
    admin_page.select_option('select[name="itemId"]', index=1)
    admin_page.fill('input[name="qty"]', "2")
    with admin_page.expect_navigation():
        admin_page.click('button:has-text("Save")')
    assert "saved" in admin_page.content().lower()

    admin_page.goto(f"{ui_base_url}/tracker?date={date}")
    assert item_name_selected.split(" (")[0] in admin_page.content()


def test_create_issue_without_department_shows_error(admin_page, ui_base_url):
    date = unique_date(21)
    admin_page.goto(f"{ui_base_url}/issue")
    admin_page.fill('input[name="date"]', date)
    admin_page.select_option('select[name="itemId"]', index=1)
    admin_page.fill('input[name="qty"]', "1")
    with admin_page.expect_navigation():
        admin_page.evaluate("""() => {
            const form = document.querySelector('form[action=""], form:not([action])') || document.forms[0];
            form.noValidate = true;
            form.querySelector('input[name="departmentName"]').value = '';
            form.requestSubmit();
        }""")
    assert "Department is required" in admin_page.content()


def test_kitchen_role_cannot_access_stock_issue_page(kitchen_page, ui_base_url):
    resp = kitchen_page.goto(f"{ui_base_url}/issue")
    assert resp.status < 500
    assert "/issue" not in kitchen_page.url
