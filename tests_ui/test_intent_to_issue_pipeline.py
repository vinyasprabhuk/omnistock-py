"""Intent -> (manually) Stock Issue -> Daily Tracker. Intent has no
automated bridge to Kitchen Requirement/Stock Issue in the current code
(confirmed by reading app/views/intent.py -- Confirm only flips
IntentDay.status, it doesn't create a requirement) -- this is a
real-workflow test: generate Intent's ingredient forecast, then issue
stock for that same quantity, exactly as kitchen staff would do by hand
today, and confirm Daily Tracker picks it up correctly."""
from __future__ import annotations

from conftest import unique_date


def _generate_intent(page, ui_base_url, date: str):
    page.goto(f"{ui_base_url}/intent?day={date}&week={date}")
    with page.expect_navigation():
        page.evaluate(
            """(date) => {
                const form = document.querySelector('form[action*="/intent/generate"]');
                if (!form) return;
                const dateInput = form.querySelector('input[name="date"]');
                if (dateInput) dateInput.value = date;
                form.requestSubmit();
            }""",
            date,
        )
    page.wait_for_load_state("networkidle")


class TestIntentGeneration:
    def test_generate_intent_produces_ingredient_list(self, admin_page, ui_base_url):
        date = unique_date(30)
        _generate_intent(admin_page, ui_base_url, date)
        content = admin_page.content()
        assert "Traceback" not in content
        assert "Internal Server Error" not in content
        # Either a real ingredient table or an explicit "gaps" flash --
        # both are valid outcomes of Generate, a raw crash is not.
        assert "Generated" in content or "gaps" in content.lower()

    def test_generate_without_date_shows_error(self, admin_page, ui_base_url):
        admin_page.goto(f"{ui_base_url}/intent")
        with admin_page.expect_navigation():
            admin_page.evaluate("""() => {
                const form = document.querySelector('form[action*="/intent/generate"]');
                form.noValidate = true;
                const dateInput = form.querySelector('input[name="date"]');
                if (dateInput) dateInput.value = '';
                form.requestSubmit();
            }""")
        assert "Missing branch or date" in admin_page.content()

    def test_kitchen_role_cannot_access_intent_page(self, kitchen_page, ui_base_url):
        resp = kitchen_page.goto(f"{ui_base_url}/intent")
        assert resp.status < 500
        assert "/intent" not in kitchen_page.url


class TestIntentToStockIssueBridge:
    def test_issuing_intents_suggested_qty_reflects_on_tracker(self, admin_page, ui_base_url):
        gen_date = unique_date(31)
        _generate_intent(admin_page, ui_base_url, gen_date)

        # Ingredient rows carry data-name, and qty lives in an <input
        # class="ing-input"> (an editable Save-per-row field), not plain
        # cell text -- read it via .value, not textContent.
        ingredient = admin_page.evaluate(
            """() => {
                const rows = [...document.querySelectorAll('#ing-table tbody tr[data-name]')];
                for (const r of rows) {
                    const input = r.querySelector('input.ing-input');
                    const qty = input ? parseFloat(input.value) : NaN;
                    if (!isNaN(qty) && qty > 0) {
                        return {name: r.children[0].textContent.trim(), qty: qty};
                    }
                }
                return null;
            }"""
        )
        if ingredient is None:
            import pytest
            pytest.skip("No ingredients with qty > 0 generated for this date (likely no recipe/sales "
                        "history available on the test branch to forecast from)")

        issue_date = unique_date(32)
        admin_page.goto(f"{ui_base_url}/issue")
        admin_page.fill('input[name="date"]', issue_date)
        admin_page.fill('input[name="departmentName"]', "Intent Bridge Test")
        matched = admin_page.evaluate(
            """(name) => {
                const select = document.querySelector('select[name="itemId"]');
                const opt = [...select.options].find(o => o.textContent.includes(name));
                if (!opt) return false;
                select.value = opt.value;
                return true;
            }""",
            ingredient["name"],
        )
        if not matched:
            import pytest
            pytest.skip(f"Intent ingredient {ingredient['name']!r} has no matching Item Master row "
                        "in the Stock Issue item picker")

        admin_page.fill('input[name="qty"]', str(ingredient["qty"]))
        with admin_page.expect_navigation():
            admin_page.click('button:has-text("Save")')

        admin_page.goto(f"{ui_base_url}/tracker?date={issue_date}")
        cells = admin_page.evaluate(
            """(name) => {
                const rows = [...document.querySelectorAll('tbody tr')];
                const row = rows.find(r => r.textContent.includes(name));
                return row ? [...row.children].map(td => td.textContent.trim()) : null;
            }""",
            ingredient["name"],
        )
        assert cells is not None, f"issued item {ingredient['name']!r} not found on Daily Tracker"
        assert float(cells[5]) == ingredient["qty"], (
            f"Daily Tracker Issued column should match the qty Intent forecast "
            f"({ingredient['qty']}), got {cells[5]}"
        )
