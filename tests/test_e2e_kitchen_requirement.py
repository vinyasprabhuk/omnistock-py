"""End-to-end coverage of the Kitchen Requirement lifecycle: upload ->
review -> confirm (auto-issues stock) -> Daily Tracker reflects it, and
upload -> reject (deletes outright). This is the most complex, most
recently-changed feature in the app, and the least covered by the
existing suite -- exercised here via a real generated .xlsx in the exact
format parse_kitchen_excel expects, matched against real Item Master
rows so the AUTO-match path runs for real, not mocked.
"""
from __future__ import annotations

import io

from app.dates import date_key_to_db
from tests.conftest import build_kitchen_upload_xlsx, csrf_token, login, make_user


def _upload(client, token, branch_id, date="2026-08-25", filename="test.xlsx", force=False, items=None):
    items = items or {"SOUTH INDIAN": [("Sugar", 2.0, "Kg"), ("Toor Dhal", 6.0, "Kg")]}
    data = build_kitchen_upload_xlsx(items)
    payload = {
        "file": (io.BytesIO(data), filename),
        "branchId": branch_id,
        "date": date,
        "_csrf_token": token,
    }
    if force:
        payload["force"] = "true"
    return client.post("/kitchen/upload", data=payload, content_type="multipart/form-data")


def _admin_client(full_app, full_db_conn, branch_id):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


class TestUploadAndDuplicateDetection:
    def test_upload_creates_requirement_with_automatched_items(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id)
        assert resp.status_code == 302
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]

        rows = full_db_conn.execute(
            "SELECT matchedItemId, status FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchall()
        assert len(rows) == 2
        assert all(r["matchedItemId"] is not None for r in rows), "real item names should AUTO-match"

    def test_reupload_same_file_without_force_is_flagged_duplicate(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        _upload(client, token, branch_id, filename="dup.xlsx")
        resp = _upload(client, token, branch_id, filename="dup.xlsx")
        assert resp.status_code == 200  # renders duplicate.html, no redirect
        assert b"duplicate" in resp.data.lower() or b"already" in resp.data.lower()

    def test_reupload_with_force_creates_a_second_requirement(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        r1 = _upload(client, token, branch_id, filename="dup2.xlsx")
        r2 = _upload(client, token, branch_id, filename="dup2.xlsx", force=True)
        assert r2.status_code == 302
        assert r1.headers["Location"] != r2.headers["Location"]


class TestConfirmFlow:
    def test_confirm_blocks_kitchen_role(self, full_app, full_db_conn, branch_id):
        admin = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(admin)
        resp = _upload(admin, token, branch_id, filename="k1.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]

        kitchen_client = full_app.test_client()
        _, kuser, kpass = make_user(full_db_conn, "KITCHEN", branch_id)
        login(kitchen_client, kuser, kpass)
        ktoken = csrf_token(kitchen_client)
        resp2 = kitchen_client.post(
            f"/kitchen/review/{requirement_id}/confirm",
            data={"_csrf_token": ktoken, "date": "2026-08-25", "branchId": branch_id},
        )
        assert resp2.status_code == 403

    def test_approve_does_not_issue_stock_only_explicit_issue_does(
        self, full_app, full_db_conn, branch_id
    ):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="k2.xlsx", items={
            "SOUTH INDIAN": [("Sugar", 2.0, "Kg")],
            "CHINESE": [("Butter", 1.0, "Kg")],
        })
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]

        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]
        resp2 = client.post(
            f"/kitchen/review/{requirement_id}/confirm",
            data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "comment": "looks fine"},
        )
        assert resp2.status_code == 302
        after_approve = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]
        assert after_approve == before, "Approve alone must not create any StockIssue"

        req_row = full_db_conn.execute(
            "SELECT status, confirmedAt FROM KitchenRequirement WHERE id = ?", (requirement_id,)
        ).fetchone()
        assert req_row["status"] == "APPROVED"
        assert req_row["confirmedAt"] is not None

        # Approve alone (confirmedAt set, status='APPROVED') must not show up
        # in Daily Tracker's "Kitchen Req." column either -- that column is
        # gated on status='ISSUED', same as actual stock movement, so an
        # admin adjusting qty against real stock-room availability never
        # shows a number here that then changes again at Issue time.
        from app.services.calculations import get_daily_tracker
        rows_before_issue = get_daily_tracker(full_db_conn, branch_id, date_key_to_db("2026-08-25"))
        sugar_before = next(r for r in rows_before_issue if r["itemName"] == "Sugar")
        assert sugar_before["kitchenRequirement"] == 0.0
        assert sugar_before["issued"] == 0.0

        tracker_before_issue = client.get(f"/tracker?date=2026-08-25&branchId={branch_id}")
        assert b"Sugar" not in tracker_before_issue.data or b"0.00" in tracker_before_issue.data

        resp3 = client.post(
            f"/kitchen/review/{requirement_id}/issue",
            data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id},
        )
        assert resp3.status_code == 302
        after_issue = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]
        assert after_issue - before == 2, "one StockIssue per department (SOUTH INDIAN, CHINESE), only after Issue"

        issues = full_db_conn.execute(
            "SELECT sourceRequirementId FROM StockIssue ORDER BY createdAt DESC LIMIT 2"
        ).fetchall()
        assert all(i["sourceRequirementId"] == requirement_id for i in issues)

        req_row2 = full_db_conn.execute("SELECT status, issuedAt FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
        assert req_row2["status"] == "ISSUED"
        assert req_row2["issuedAt"] is not None

        tracker_resp = client.get(f"/tracker?date=2026-08-25&branchId={branch_id}")
        assert tracker_resp.status_code == 200
        assert b"Sugar" in tracker_resp.data

        rows_after_issue = get_daily_tracker(full_db_conn, branch_id, date_key_to_db("2026-08-25"))
        sugar_after = next(r for r in rows_after_issue if r["itemName"] == "Sugar")
        assert sugar_after["kitchenRequirement"] == 2.0
        assert sugar_after["issued"] == 2.0

    def test_double_issue_is_blocked(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="k2b.xlsx", items={
            "SOUTH INDIAN": [("Sugar", 2.0, "Kg")],
        })
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        client.post(f"/kitchen/review/{requirement_id}/issue",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]

        resp2 = client.post(
            f"/kitchen/review/{requirement_id}/issue",
            data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id},
            follow_redirects=True,
        )
        assert b"must be approved before it can be issued" in resp2.data
        after = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]
        assert after == before

    def test_kitchen_role_blocked_from_issue(self, full_app, full_db_conn, branch_id):
        admin_client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(admin_client)
        resp = _upload(admin_client, token, branch_id, filename="k2c.xlsx", items={
            "SOUTH INDIAN": [("Sugar", 2.0, "Kg")],
        })
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        admin_client.post(f"/kitchen/review/{requirement_id}/confirm",
                           data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})

        kitchen_client = full_app.test_client()
        _, kusername, kpassword = make_user(full_db_conn, "KITCHEN", branch_id)
        login(kitchen_client, kusername, kpassword)
        ktoken = csrf_token(kitchen_client)
        resp2 = kitchen_client.post(
            f"/kitchen/review/{requirement_id}/issue",
            data={"_csrf_token": ktoken, "date": "2026-08-25", "branchId": branch_id},
        )
        assert resp2.status_code == 403

    def test_admin_edits_approved_qty_before_issue_flows_into_stock_issue(
        self, full_app, full_db_conn, branch_id
    ):
        """Regression test for the old latent bug: editing qty after
        approval must be reflected in the eventually-issued StockIssueItem
        qty, since issuing is now deferred until the explicit Issue step."""
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="k2d.xlsx", items={
            "SOUTH INDIAN": [("Sugar", 4.0, "Kg")],
        })
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})

        item_row = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchone()
        client.post(f"/requirements/item/{item_row['id']}/update",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "qty": "2"})

        client.post(f"/kitchen/review/{requirement_id}/issue",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})

        issued_qty = full_db_conn.execute(
            "SELECT sii.qty FROM StockIssueItem sii JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.sourceRequirementId = ?", (requirement_id,)
        ).fetchone()
        assert issued_qty["qty"] == 2.0

        resp_after = client.post(f"/requirements/item/{item_row['id']}/update",
                                  data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "qty": "9"},
                                  follow_redirects=True)
        assert b"not found or not approved yet" in resp_after.data
        still_qty = full_db_conn.execute("SELECT qty FROM KitchenRequirementItem WHERE id = ?", (item_row["id"],)).fetchone()
        assert still_qty["qty"] == 2.0, "qty edit must be blocked once issued"

    def test_admin_zeroing_approved_qty_removes_item_not_zero_qty_issue(
        self, full_app, full_db_conn, branch_id
    ):
        """Zeroing a qty on the Approved page must remove the row outright
        (same convention as the Kitchen-side edit flow), not leave a
        zero-qty line that would show up as a zero StockIssueItem once
        issued."""
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="k2e.xlsx", items={
            "SOUTH INDIAN": [("Sugar", 4.0, "Kg"), ("Toor Dhal", 6.0, "Kg")],
        })
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})

        sugar_row = full_db_conn.execute(
            "SELECT kri.id FROM KitchenRequirementItem kri JOIN Item i ON i.id = kri.matchedItemId "
            "WHERE kri.requirementId = ? AND i.name = 'Sugar'", (requirement_id,)
        ).fetchone()
        client.post(f"/requirements/item/{sugar_row['id']}/update",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "qty": "0"})

        remaining = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchall()
        assert len(remaining) == 1, "zeroed item should be deleted, not left as a zero-qty row"

        # approving/issuing must still work fine with fewer items
        client.post(f"/kitchen/review/{requirement_id}/issue",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        issued_items = full_db_conn.execute(
            "SELECT sii.qty FROM StockIssueItem sii JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.sourceRequirementId = ?", (requirement_id,)
        ).fetchall()
        assert len(issued_items) == 1
        assert issued_items[0]["qty"] == 6.0

    def test_double_confirm_is_blocked(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="k3.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        before = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        after = full_db_conn.execute("SELECT COUNT(*) FROM StockIssue").fetchone()[0]
        assert after == before, "re-confirming an already-confirmed requirement must not double-issue stock"

    def test_confirm_blocked_with_unmatched_rows(self, full_app, full_db_conn, branch_id):
        # match_item always attaches a best-guess matchedItemId even at
        # MANUAL confidence (see match_item.py) -- a garbage item NAME
        # alone never produces matchedItemId=NULL through the real upload
        # path, only an ambiguous/unrecognized unit does, which the
        # parser drops as an unparseable row before it ever reaches the
        # DB. So this exercises the manual "add row" path instead, which
        # can add a row with no matchedItemId at all -- the same shape
        # confirm_kitchen_requirement's unmatched check guards against.
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="k4.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/item/add", data={
            "_csrf_token": token, "departmentName": "SOUTH INDIAN", "itemText": "Mystery Item",
            "matchedItemId": "", "qty": "1", "unit": "Kg",
        })

        resp2 = client.post(f"/kitchen/review/{requirement_id}/confirm",
                             data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id},
                             follow_redirects=True)
        assert b"need an item selected" in resp2.data
        row = full_db_conn.execute("SELECT confirmedAt FROM KitchenRequirement WHERE id = ?", (requirement_id,)).fetchone()
        assert row["confirmedAt"] is None


class TestRejectFlow:
    def test_reject_without_comment_is_blocked(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="r1.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/reject",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "comment": ""})
        still_there = full_db_conn.execute(
            "SELECT COUNT(*) FROM KitchenRequirement WHERE id = ?", (requirement_id,)
        ).fetchone()[0]
        assert still_there == 1

    def test_reject_with_comment_deletes_requirement_items_and_upload(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="r2.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        upload_id = full_db_conn.execute(
            "SELECT uploadId FROM KitchenRequirement WHERE id = ?", (requirement_id,)
        ).fetchone()["uploadId"]

        resp2 = client.post(f"/kitchen/review/{requirement_id}/reject",
                             data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id,
                                   "comment": "wrong file"})
        assert resp2.status_code == 302

        assert full_db_conn.execute(
            "SELECT COUNT(*) FROM KitchenRequirement WHERE id = ?", (requirement_id,)
        ).fetchone()[0] == 0
        assert full_db_conn.execute(
            "SELECT COUNT(*) FROM KitchenRequirementItem WHERE requirementId = ?", (requirement_id,)
        ).fetchone()[0] == 0
        assert full_db_conn.execute(
            "SELECT COUNT(*) FROM Upload WHERE id = ?", (upload_id,)
        ).fetchone()[0] == 0

    def test_reupload_same_content_after_reject_is_not_flagged_duplicate(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="r3.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/reject",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "comment": "bad"})

        resp2 = _upload(client, token, branch_id, filename="r3.xlsx")
        assert resp2.status_code == 302, "same content re-uploaded after reject must not trip the duplicate check"

    def test_reject_blocked_on_already_confirmed_requirement(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="r4.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        client.post(f"/kitchen/review/{requirement_id}/reject",
                     data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id, "comment": "oops"})
        still_confirmed = full_db_conn.execute(
            "SELECT confirmedAt FROM KitchenRequirement WHERE id = ?", (requirement_id,)
        ).fetchone()
        assert still_confirmed is not None and still_confirmed["confirmedAt"] is not None


class TestRequirementsPageBatchesAndPending:
    def test_two_uploads_same_date_stay_separate_requirements(self, full_app, full_db_conn, branch_id):
        """Each upload is its own KitchenRequirement (unique id), so
        distinct-batch separation doesn't need a "Batch N" label -- the
        two requirements' items must simply not be merged together."""
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        batch_items = [
            {"SOUTH INDIAN": [("Sugar", 2.0, "Kg")]},
            {"SOUTH INDIAN": [("Sugar", 3.0, "Kg")]},  # different qty -> different file hash, not a duplicate
        ]
        requirement_ids = []
        for fn, items in zip(("b1.xlsx", "b2.xlsx"), batch_items):
            resp = _upload(client, token, branch_id, filename=fn, items=items)
            assert resp.status_code == 302, resp.get_data(as_text=True)[:300]
            requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
            requirement_ids.append(requirement_id)
            client.post(f"/kitchen/review/{requirement_id}/confirm",
                        data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})

        assert len(set(requirement_ids)) == 2
        rows = full_db_conn.execute(
            "SELECT DISTINCT requirementId, qty FROM KitchenRequirementItem WHERE requirementId IN (?, ?)",
            requirement_ids,
        ).fetchall()
        qtys = sorted(r["qty"] for r in rows)
        assert qtys == [2.0, 3.0], "both requirements' items must exist independently, not merged"

        page = client.get(f"/requirements?date=2026-08-25&branchId={branch_id}")
        assert page.status_code == 200

    def test_pending_requirement_shows_on_requirements_page_with_approve_reject(
        self, full_app, full_db_conn, branch_id
    ):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        _upload(client, token, branch_id, filename="p1.xlsx")

        page = client.get(f"/requirements?date=2026-08-25&branchId={branch_id}")
        body = page.get_data(as_text=True)
        assert "Pending Review" in body
        assert ">Approve<" in body and ">Reject<" in body

    def test_confirmed_qty_editable_inline_unconfirmed_is_not(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="q1.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        item_id = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementItem WHERE requirementId = ? LIMIT 1", (requirement_id,)
        ).fetchone()["id"]

        # Not confirmed yet -- update route should refuse.
        resp_early = client.post(f"/requirements/item/{item_id}/update",
                                  data={"_csrf_token": token, "qty": "99", "date": "2026-08-25", "branchId": branch_id})
        qty_before = full_db_conn.execute("SELECT qty FROM KitchenRequirementItem WHERE id = ?", (item_id,)).fetchone()["qty"]
        assert qty_before != 99

        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        client.post(f"/requirements/item/{item_id}/update",
                    data={"_csrf_token": token, "qty": "99", "date": "2026-08-25", "branchId": branch_id})
        qty_after = full_db_conn.execute("SELECT qty FROM KitchenRequirementItem WHERE id = ?", (item_id,)).fetchone()["qty"]
        assert qty_after == 99


class TestExports:
    def test_combined_and_per_batch_export_download(self, full_app, full_db_conn, branch_id):
        client = _admin_client(full_app, full_db_conn, branch_id)
        token = csrf_token(client)
        resp = _upload(client, token, branch_id, filename="e1.xlsx")
        requirement_id = resp.headers["Location"].rsplit("/", 1)[-1]
        client.post(f"/kitchen/review/{requirement_id}/confirm",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})
        client.post(f"/kitchen/review/{requirement_id}/issue",
                    data={"_csrf_token": token, "date": "2026-08-25", "branchId": branch_id})

        combined = client.get(f"/api/export/requirements?date=2026-08-25&branchId={branch_id}")
        assert combined.status_code == 200
        assert combined.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        per_batch = client.get(
            f"/api/export/requirements?date=2026-08-25&branchId={branch_id}&requirementId={requirement_id}"
        )
        assert per_batch.status_code == 200
        assert "batch1" in per_batch.headers["Content-Disposition"]
