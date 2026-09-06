"""
Real-browser E2E suite -- runs against a LIVE deployed instance (test
env by default), not the Flask test client the way tests/ does. Meant
to be re-run after every deployment to test.inventory.mokshamveg.com to
catch anything a code-level pytest run can't: template bugs, JS bugs,
role-based nav visibility, actual multi-step click-through flows.

Requires Google Chrome installed locally -- Playwright's own bundled
Chromium download doesn't support this host's macOS version, so every
fixture here launches via channel="chrome" (the system browser)
instead of the default bundled one.

Configuration is entirely via environment variables -- no credentials
are ever hardcoded in this suite, since it's committed to git:

    UI_TEST_BASE_URL       Defaults to https://test.inventory.mokshamveg.com
                            NEVER point this at production.
    UI_TEST_ADMIN_USER / UI_TEST_ADMIN_PASS       (required for most tests)
    UI_TEST_KITCHEN_USER / UI_TEST_KITCHEN_PASS   (required for Kitchen flows)
    UI_TEST_STORE_USER / UI_TEST_STORE_PASS       (optional)
    UI_TEST_MANAGER_USER / UI_TEST_MANAGER_PASS   (optional)
    UI_TEST_VIEWER_USER / UI_TEST_VIEWER_PASS     (optional)
    UI_TEST_DEPTLEAD_USER / UI_TEST_DEPTLEAD_PASS (optional)

A role whose env vars aren't set has its tests skipped (not failed) --
see `role_credentials` below. This suite creates its own throwaway
KitchenRequirement/Purchase/etc. rows on every run (always for a
far-future date so it never collides with real data) and DOES NOT clean
them up automatically -- see tools/cleanup_ui_test_data.py to sweep
them after a run.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest

BASE_URL = os.environ.get("UI_TEST_BASE_URL", "https://test.inventory.mokshamveg.com")

if "inventory.mokshamveg.com" in BASE_URL and "test." not in BASE_URL:
    raise RuntimeError(
        f"UI_TEST_BASE_URL={BASE_URL!r} looks like production, not the test "
        "subdomain -- refusing to run. This suite creates and mutates real "
        "records and must never target inventory.mokshamveg.com directly."
    )

# A fresh date namespace for every run, so re-running this suite (e.g.
# on every deployment, possibly the same day) never collides with a
# requirement/purchase a PREVIOUS run already carried through to
# Approved/Issued for that same date -- hardcoding one literal date
# caused exactly that collision the first time this suite ran twice.
# Base offset is today + 500 days (always far past real ops) plus a
# random 0-300 day jitter seeded fresh per run, so even two runs on the
# same calendar day land on different dates almost certainly.
RUN_TAG = uuid.uuid4().hex[:8]
_BASE_DAY = date.today() + timedelta(days=500 + (int(RUN_TAG, 16) % 300))


def unique_date(offset: int = 0) -> str:
    """A unique-per-run date string (YYYY-MM-DD), offset by `offset`
    days so different tests within one run each get their own date too."""
    return (_BASE_DAY + timedelta(days=offset)).strftime("%Y-%m-%d")


def _role_creds(role: str) -> tuple[str, str] | None:
    user = os.environ.get(f"UI_TEST_{role}_USER")
    pw = os.environ.get(f"UI_TEST_{role}_PASS")
    if user and pw:
        return user, pw
    return None


ROLE_CREDS = {
    "ADMIN": _role_creds("ADMIN"),
    "KITCHEN": _role_creds("KITCHEN"),
    "STORE": _role_creds("STORE"),
    "MANAGER": _role_creds("MANAGER"),
    "VIEWER": _role_creds("VIEWER"),
    "DEPTLEAD": _role_creds("DEPTLEAD"),
}


def require_role(role: str):
    """Use as a decorator-style skip guard at the top of a test:
    require_role("KITCHEN") -- skips with a clear reason instead of
    failing when that role's env vars aren't configured for this run."""
    if ROLE_CREDS.get(role) is None:
        pytest.skip(f"UI_TEST_{role}_USER/UI_TEST_{role}_PASS not set -- skipping {role} coverage")
    return ROLE_CREDS[role]


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, "channel": "chrome"}


@pytest.fixture()
def ui_base_url():
    # Named distinctly from pytest-playwright/pytest-base-url's own
    # session-scoped "base_url" fixture -- redefining that name here
    # caused a ScopeMismatch (theirs is session-scoped, this one isn't).
    return BASE_URL


def login_as(page, base_url, username: str, password: str):
    page.goto(f"{base_url}/login")
    page.fill('input[type="text"]', username)
    page.fill('input[type="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def logout(page, base_url):
    page.goto(f"{base_url}/kitchen")  # any authenticated page with the nav
    btn = page.locator('button:has-text("Sign out")')
    if btn.count():
        btn.first.click()
        page.wait_for_load_state("networkidle")


@pytest.fixture()
def admin_page(browser, ui_base_url):
    # A dedicated browser context (own cookie jar), not the shared `page`
    # fixture -- a test using both admin_page and kitchen_page needs two
    # genuinely independent logged-in sessions, not one page whose
    # session cookie gets overwritten by whichever fixture logs in second.
    user, pw = require_role("ADMIN")
    context = browser.new_context()
    page = context.new_page()
    login_as(page, ui_base_url, user, pw)
    yield page
    context.close()


@pytest.fixture()
def kitchen_page(browser, ui_base_url):
    user, pw = require_role("KITCHEN")
    context = browser.new_context()
    page = context.new_page()
    login_as(page, ui_base_url, user, pw)
    yield page
    context.close()
