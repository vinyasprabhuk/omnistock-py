"""Login/logout -- positive and negative."""
from __future__ import annotations

from conftest import login_as, require_role


def test_login_with_correct_credentials_succeeds(page, ui_base_url):
    user, pw = require_role("ADMIN")
    login_as(page, ui_base_url, user, pw)
    assert "login" not in page.url
    assert page.locator("text=Authenticated as").count() > 0


def test_login_with_wrong_password_fails(page, ui_base_url):
    user, _ = require_role("ADMIN")
    login_as(page, ui_base_url, user, "definitely-the-wrong-password")
    assert "/login" in page.url or page.locator("text=Invalid").count() > 0


def test_login_with_unknown_username_fails(page, ui_base_url):
    login_as(page, ui_base_url, "no_such_user_ui_test", "whatever123")
    assert "/login" in page.url or page.locator("text=Invalid").count() > 0


def test_logout_ends_session(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/kitchen")
    admin_page.locator('button:has-text("Sign out")').first.click()
    admin_page.wait_for_load_state("networkidle")
    # A protected page must now bounce back to login.
    admin_page.goto(f"{ui_base_url}/tracker")
    assert "/login" in admin_page.url


def test_visiting_protected_page_while_logged_out_redirects_to_login(page, ui_base_url):
    page.goto(f"{ui_base_url}/tracker")
    assert "/login" in page.url
