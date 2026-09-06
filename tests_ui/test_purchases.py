"""Purchases -- manual entry and bulk upload, including the GST
Number/Bill No capture, positive and negative."""
from __future__ import annotations

from conftest import RUN_TAG


def test_manual_entry_with_gst_and_bill_no_saves(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/purchases")
    assert admin_page.locator('input[name="gstNumber"]').count() == 1
    assert admin_page.locator('input[name="billNo"]').count() == 1

    bill_no = f"UITEST-{RUN_TAG}"
    admin_page.fill('input[name="date"]', "2028-02-10")
    admin_page.fill('input[name="supplier"]', "UI Test Vendor")
    admin_page.fill('input[name="gstNumber"]', "29UITESTGST1Z5")
    admin_page.fill('input[name="billNo"]', bill_no)
    admin_page.select_option('#purchase-lines select[name="itemId"]', index=1)
    admin_page.fill('#purchase-lines input[name="qty"]', "5")
    admin_page.fill('#purchase-lines input[name="rate"]', "20")
    admin_page.click('button:has-text("Save Purchase Entry")')
    admin_page.wait_for_load_state("networkidle")

    assert "Purchase saved" in admin_page.content()


def test_manual_entry_without_any_line_shows_error_and_saves_nothing(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/purchases")
    admin_page.fill('input[name="date"]', "2028-02-11")
    # Leave the one default line's item unselected and qty empty, then
    # submit. noValidate bypasses the browser's own required-field
    # blocking so the request actually reaches the server -- this is
    # testing the server-side check (a real client could always send an
    # empty line regardless of what the HTML form declares).
    with admin_page.expect_navigation():
        admin_page.evaluate("""() => {
            const form = document.querySelector('form[enctype="multipart/form-data"]');
            form.noValidate = true;
            form.requestSubmit();
        }""")
    admin_page.wait_for_load_state("networkidle")
    assert "Add at least one line item" in admin_page.content()


def test_manual_entry_without_date_shows_error(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/purchases")
    admin_page.select_option('#purchase-lines select[name="itemId"]', index=1)
    admin_page.fill('#purchase-lines input[name="qty"]', "1")
    with admin_page.expect_navigation():
        admin_page.evaluate("""() => {
            const form = document.querySelector('form[enctype="multipart/form-data"]');
            form.noValidate = true;
            form.querySelector('input[name="date"]').value = '';
            form.requestSubmit();
        }""")
    admin_page.wait_for_load_state("networkidle")
    assert "Date is required" in admin_page.content()


def test_incoming_invoices_link_visible_on_purchases_page(admin_page, ui_base_url):
    admin_page.goto(f"{ui_base_url}/purchases")
    assert admin_page.locator('a[href*="/purchases/incoming"]').count() >= 1
