"""e2e tests against a REAL "Outlet-Item Wise Report" POS export the
user provided (see tests/fixtures/real_samples/, gitignored -- real
business data). Skips gracefully if not present locally."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parsing.dish_sales_excel import parse_dish_sales_file
from tests.conftest import csrf_token, login, make_user

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "real_samples"
SALE_REPORT_FILE = FIXTURES_DIR / "dish_sale_report.xlsx"

pytestmark = pytest.mark.skipif(not SALE_REPORT_FILE.exists(), reason=f"real sample not present: {SALE_REPORT_FILE}")


class TestParserAgainstRealFile:
    def test_parses_real_rows_with_correct_date_and_known_item(self):
        rows = parse_dish_sales_file(str(SALE_REPORT_FILE))
        assert len(rows) > 0
        assert all(r["date"] == "2026-08-16" for r in rows)

        butter_roti = next((r for r in rows if r["item"] == "Butter Roti"), None)
        assert butter_roti is not None
        assert butter_roti["qty"] == 2.0
        assert butter_roti["restaurant"] == "Moksham Veg Restaurant"

    def test_summary_rows_are_excluded(self):
        rows = parse_dish_sales_file(str(SALE_REPORT_FILE))
        items = {r["item"] for r in rows}
        # "Total"/"Min."/"Max."/"Avg." live in the marker column, not the
        # item column, but confirm none of them leaked through as if they
        # were real dish names.
        assert "Total" not in items
        assert "Min." not in items
        assert "Max." not in items
        assert "Avg." not in items


class TestUploadFlowAgainstRealFile:
    def test_upload_creates_dish_sale_rows_and_auto_creates_dishes(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "ADMIN", None)
        login(client, username, password)
        token = csrf_token(client)

        dishes_before = full_db_conn.execute("SELECT COUNT(*) FROM Dish").fetchone()[0]
        with open(SALE_REPORT_FILE, "rb") as f:
            resp = client.post("/intent/upload-sales", data={
                "_csrf_token": token, "week": "2026-08-16", "branchId": branch_id,
                "files": (f, "dish_sale_report.xlsx"),
            }, content_type="multipart/form-data", follow_redirects=True)
        assert resp.status_code == 200
        assert b"day(s)" in resp.data or b"sale rows" in resp.data

        dishes_after = full_db_conn.execute("SELECT COUNT(*) FROM Dish").fetchone()[0]
        assert dishes_after > dishes_before, "new dishes should be auto-created from real item names"

        from app.dates import date_key_to_db
        sale_count = full_db_conn.execute(
            "SELECT COUNT(*) FROM DishSale WHERE date = ?", (date_key_to_db("2026-08-16"),)
        ).fetchone()[0]
        assert sale_count > 0

    def test_reuploading_same_date_replaces_not_duplicates(self, full_app, full_db_conn, branch_id):
        client = full_app.test_client()
        _, username, password = make_user(full_db_conn, "ADMIN", None)
        login(client, username, password)
        token = csrf_token(client)

        for _ in range(2):
            with open(SALE_REPORT_FILE, "rb") as f:
                client.post("/intent/upload-sales", data={
                    "_csrf_token": token, "week": "2026-08-16", "branchId": branch_id,
                    "files": (f, "dish_sale_report.xlsx"),
                }, content_type="multipart/form-data")

        from app.dates import date_key_to_db
        upload_count = full_db_conn.execute(
            "SELECT COUNT(*) FROM DishSaleUpload WHERE date = ?", (date_key_to_db("2026-08-16"),)
        ).fetchone()[0]
        assert upload_count == 1, "re-uploading the same date must replace, not create a second upload record"
