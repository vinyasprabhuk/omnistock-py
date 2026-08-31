"""e2e tests against REAL kitchen upload files the user provided, kept
outside git (see tests/fixtures/real_samples/, gitignored -- real
business data). Skips gracefully if a given sample isn't present
locally, so this file is safe to run (and safe to be absent) anywhere.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import csrf_token, login, make_user

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "real_samples"
MULTI_SHEET_FILE = FIXTURES_DIR / "kitchen_requirement_multi_dated_sheets.xlsx"


def _admin_client(full_app, full_db_conn, branch_id):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


@pytest.mark.skipif(not MULTI_SHEET_FILE.exists(), reason=f"real sample not present: {MULTI_SHEET_FILE}")
class TestMultiDatedSheetWorkbook:
    """This real file has TWO date-named sheets ('29.08.2026' and
    '28.08.2026') -- parse_kitchen_excel's documented behavior is that
    when a workbook has 2+ dated sheets, only the LATEST is parsed. On
    this real file, 'Mustard' is 0.5 Kg on the 29th's sheet but 0.1 Kg on
    the 28th's -- a real, non-synthetic check that the right sheet wins.
    """

    def test_only_latest_dated_sheet_is_parsed(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)

        with open(MULTI_SHEET_FILE, "rb") as f:
            resp = client.post("/kitchen/upload", data={
                "file": (f, "sunday.xlsx"),
                "branchId": branch_id, "date": "2026-08-29", "_csrf_token": token,
            }, content_type="multipart/form-data")
        assert resp.status_code == 302
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]

        row = full_db_conn.execute(
            "SELECT kri.qty FROM KitchenRequirementItem kri "
            "WHERE kri.requirementId = ? AND kri.extractedText = 'Mustard'",
            (requirement_id,),
        ).fetchone()
        assert row is not None, "Mustard should have been extracted at all"
        assert row["qty"] == 0.5, (
            "qty must come from the LATEST dated sheet (29.08.2026's 0.5), "
            "not the older 28.08.2026 sheet's 0.1 -- if this is 0.1, the "
            "multi-sheet 'latest wins' heuristic has regressed"
        )

    def test_all_four_department_blocks_extracted(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        with open(MULTI_SHEET_FILE, "rb") as f:
            resp = client.post("/kitchen/upload", data={
                "file": (f, "sunday2.xlsx"),
                "branchId": branch_id, "date": "2026-08-29", "_csrf_token": token,
            }, content_type="multipart/form-data")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]

        # find_or_create_department matches case-insensitively against an
        # existing department -- "Dosa" already exists in the pristine
        # data, so a sheet header of "DOSA" resolves to that existing
        # row's stored casing rather than creating a new all-caps one.
        # Compare case-insensitively to match that real, correct behavior.
        depts = {r["name"].upper() for r in full_db_conn.execute(
            "SELECT DISTINCT d.name FROM KitchenRequirementItem kri "
            "JOIN Department d ON d.id = kri.departmentId WHERE kri.requirementId = ?",
            (requirement_id,),
        )}
        for expected in ("SOUTH INDIAN", "COFFEE AND JUICE", "CHINESE", "DOSA"):
            assert expected in depts, f"missing department block: {expected}"

    def test_real_item_names_automatch_against_item_master(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        with open(MULTI_SHEET_FILE, "rb") as f:
            resp = client.post("/kitchen/upload", data={
                "file": (f, "sunday3.xlsx"),
                "branchId": branch_id, "date": "2026-08-29", "_csrf_token": token,
            }, content_type="multipart/form-data")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]

        total = full_db_conn.execute(
            "SELECT COUNT(*) FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchone()[0]
        matched = full_db_conn.execute(
            "SELECT COUNT(*) FROM KitchenRequirementItem WHERE requirementId = ? AND matchedItemId IS NOT NULL",
            (requirement_id,),
        ).fetchone()[0]
        assert total > 0
        # Real item names against the real Item Master should mostly
        # AUTO-match -- allow a small margin for genuinely unrecognized
        # items rather than requiring a brittle 100%.
        assert matched / total >= 0.8, f"only {matched}/{total} real items matched -- investigate before trusting this"
