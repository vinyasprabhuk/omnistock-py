"""Incoming-invoice webhook review UI. The ingestion endpoint itself is
deliberately localhost-only (see app/views/webhooks.py) -- this suite
runs from a machine that is NOT the test server, so it CANNOT seed a
pending invoice itself (confirmed: a direct POST from here gets a 403,
which is the security control working correctly, not a bug). These
tests verify the review/approve/reject UI against whatever is already
pending, and skip cleanly (not fail) when the queue is empty."""
from __future__ import annotations

import pytest


def test_webhook_endpoint_rejects_non_local_requests(admin_page, ui_base_url):
    """A quick negative check runnable from here: confirms the guard
    itself is live, even though we can't successfully ingest through it."""
    resp = admin_page.request.post(
        f"{ui_base_url}/webhooks/purchase-invoice",
        data='{"event": "invoice.pushed_to_inventory", "invoice": {"items": []}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 403


def test_webhook_endpoint_rejects_non_json_body(admin_page, ui_base_url):
    resp = admin_page.request.post(
        f"{ui_base_url}/webhooks/purchase-invoice",
        data="not json at all",
        headers={"Content-Type": "text/plain"},
    )
    # Localhost check runs first, so a non-local caller always gets 403
    # regardless of body -- this pins down that ordering rather than
    # assuming which guard fires first.
    assert resp.status == 403


def test_incoming_invoices_page_loads(admin_page, ui_base_url):
    resp = admin_page.goto(f"{ui_base_url}/purchases/incoming")
    assert resp.status == 200
    assert "Incoming Invoices" in admin_page.content()


def test_incoming_invoices_empty_state_renders_without_error(admin_page, ui_base_url):
    """Regardless of whether anything is actually queued right now, the
    page must render a clean message, never a raw error/traceback."""
    admin_page.goto(f"{ui_base_url}/purchases/incoming")
    content = admin_page.content()
    assert "Traceback" not in content
    assert "Internal Server Error" not in content
    has_events = admin_page.locator('a[href*="/purchases/incoming/"]').count() > 0
    if not has_events:
        assert "No invoices waiting for review" in content


def test_purchases_page_pending_banner_matches_incoming_queue_state(admin_page, ui_base_url):
    """The Purchases page shows a red pending-count banner only when the
    Incoming Invoices queue is actually non-empty -- checks the two
    pages agree with each other rather than drifting independently."""
    admin_page.goto(f"{ui_base_url}/purchases/incoming")
    pending_count = admin_page.locator('a[href*="/purchases/incoming/"]').count()

    admin_page.goto(f"{ui_base_url}/purchases")
    banner = admin_page.locator("text=waiting for review")
    if pending_count > 0:
        assert banner.count() >= 1
    else:
        assert banner.count() == 0


def test_review_pending_invoice_if_any_exists(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/purchases/incoming")
    links = admin_page.locator('a[href*="/purchases/incoming/"]')
    if links.count() == 0:
        pytest.skip("No pending webhook invoice queued -- ingestion is localhost-only, "
                    "run a real webhook POST from the server itself to exercise this path")

    links.first.click()
    admin_page.wait_for_load_state("networkidle")
    assert "Review Incoming Invoice" in admin_page.content()
    # Every line item must show a matched-item dropdown and a confidence/unmatched badge.
    assert admin_page.locator('select[name="itemId"]').count() >= 1
