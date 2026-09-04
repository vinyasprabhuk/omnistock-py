"""End-to-end coverage of the redesigned Kitchen Requirement lifecycle:
Request Regular/Extra Items (department-scoped, history-derived entry) ->
Pending -> Approved -> Issued, plus the Kitchen-side edit-with-reason
workflow that reopens an Approved requirement. Complements
test_e2e_kitchen_requirement.py, which covers the original Excel-upload
path and the shared Approve/Reject/Issue routes -- this file focuses on
what's new: the entry flow, the 3-stage split, and the reason-gated edit.
"""
from __future__ import annotations

from tests.conftest import csrf_token, login, make_user


def _admin_client(full_app, full_db_conn):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "ADMIN", None)
    login(client, username, password)
    return client


def _kitchen_client(full_app, full_db_conn, branch_id):
    client = full_app.test_client()
    _, username, password = make_user(full_db_conn, "KITCHEN", branch_id)
    login(client, username, password)
    return client


def _submit(client, token, branch_id, department_id, request_type, lines, date="2026-08-25"):
    """Saves one department's worth of items as a new Regular/Extra
    request (the first Save of a session -- see request_save/
    save_department_to_requirement) and returns the resulting
    requirement_id. Save redirects back to the department picker
    (?requirementId=...), not straight to the review page -- Submit
    there is just a plain navigation link once a department is saved."""
    data = {
        "_csrf_token": token, "requestType": request_type, "departmentId": department_id,
        "date": date, "branchId": branch_id,
        "itemId": [l["itemId"] for l in lines], "qty": [str(l["qty"]) for l in lines],
    }
    resp = client.post("/kitchen/request/save", data=data)
    if resp.status_code != 302:
        return None
    return resp.headers["Location"].rsplit("requirementId=", 1)[-1]


def _approve(client, token, requirement_id, branch_id, date="2026-08-25"):
    return client.post(f"/kitchen/review/{requirement_id}/confirm",
                        data={"_csrf_token": token, "date": date, "branchId": branch_id})


def _issue(client, token, requirement_id, branch_id, date="2026-08-25"):
    return client.post(f"/kitchen/review/{requirement_id}/issue",
                        data={"_csrf_token": token, "date": date, "branchId": branch_id})


def _two_items_and_dept(conn):
    items = conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 2").fetchall()
    dept = conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()
    return items, dept


class TestRegularVsExtraIndependence:
    def test_regular_and_extra_coexist_for_same_department_and_day(self, full_app, full_db_conn, branch_id):
        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items, dept = _two_items_and_dept(full_db_conn)

        regular_id = _submit(admin, token, branch_id, dept["id"], "REGULAR", [{"itemId": items[0]["id"], "qty": 5}])
        extra_id = _submit(admin, token, branch_id, dept["id"], "EXTRA", [{"itemId": items[0]["id"], "qty": 2}])
        assert regular_id and extra_id and regular_id != extra_id

        rows = full_db_conn.execute(
            "SELECT id, status, requestType FROM KitchenRequirement WHERE id IN (?, ?)", (regular_id, extra_id)
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        assert by_id[regular_id]["requestType"] == "REGULAR"
        assert by_id[extra_id]["requestType"] == "EXTRA"
        assert by_id[regular_id]["status"] == by_id[extra_id]["status"] == "PENDING"

        page = admin.get(f"/requirements?date=2026-08-25&branchId={branch_id}")
        assert page.status_code == 200

    def test_extra_lifecycle_independent_of_regular(self, full_app, full_db_conn, branch_id):
        """Approving/issuing the Extra request must not touch the
        Regular request's status at all."""
        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items, dept = _two_items_and_dept(full_db_conn)

        regular_id = _submit(admin, token, branch_id, dept["id"], "REGULAR", [{"itemId": items[0]["id"], "qty": 5}])
        extra_id = _submit(admin, token, branch_id, dept["id"], "EXTRA", [{"itemId": items[0]["id"], "qty": 2}])

        _approve(admin, token, extra_id, branch_id)
        _issue(admin, token, extra_id, branch_id)

        regular_status = full_db_conn.execute(
            "SELECT status FROM KitchenRequirement WHERE id = ?", (regular_id,)
        ).fetchone()["status"]
        assert regular_status == "PENDING", "issuing Extra must not affect the separate Regular request"


class TestKitchenEditWithReasonWorkflow:
    def _approved_requirement(self, full_app, full_db_conn, branch_id, qty=4.0):
        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items, dept = _two_items_and_dept(full_db_conn)
        req_id = _submit(admin, token, branch_id, dept["id"], "REGULAR", [{"itemId": items[0]["id"], "qty": qty}])
        _approve(admin, token, req_id, branch_id)
        return req_id, items, admin, token

    def test_request_edit_blocked_without_reason(self, full_app, full_db_conn, branch_id):
        req_id, *_ = self._approved_requirement(full_app, full_db_conn, branch_id)
        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        resp = kitchen.post(f"/kitchen/review/{req_id}/request-edit",
                             data={"_csrf_token": ktoken, "reason": ""}, follow_redirects=True)
        assert b"A reason is required" in resp.data
        status = full_db_conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (req_id,)).fetchone()["status"]
        assert status == "APPROVED", "unchanged -- no edit session was opened"

    def test_request_edit_blocked_for_non_kitchen_role(self, full_app, full_db_conn, branch_id):
        req_id, *_ = self._approved_requirement(full_app, full_db_conn, branch_id)
        admin = _admin_client(full_app, full_db_conn)
        atoken = csrf_token(admin)
        resp = admin.post(f"/kitchen/review/{req_id}/request-edit",
                           data={"_csrf_token": atoken, "reason": "need to fix qty"})
        assert resp.status_code == 403

    def test_request_edit_blocked_when_still_pending(self, full_app, full_db_conn, branch_id):
        """Nothing to unlock -- a Pending requirement is already freely
        editable via the ordinary review-screen controls."""
        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items, dept = _two_items_and_dept(full_db_conn)
        req_id = _submit(admin, token, branch_id, dept["id"], "REGULAR", [{"itemId": items[0]["id"], "qty": 4}])

        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        resp = kitchen.post(f"/kitchen/review/{req_id}/request-edit",
                             data={"_csrf_token": ktoken, "reason": "test"}, follow_redirects=True)
        assert b"Only an approved" in resp.data

    def test_request_edit_blocked_when_already_issued(self, full_app, full_db_conn, branch_id):
        req_id, items, admin, token = self._approved_requirement(full_app, full_db_conn, branch_id)
        _issue(admin, token, req_id, branch_id)

        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        resp = kitchen.post(f"/kitchen/review/{req_id}/request-edit",
                             data={"_csrf_token": ktoken, "reason": "test"}, follow_redirects=True)
        assert b"Only an approved" in resp.data

    def test_edit_submit_blocked_without_per_item_reason(self, full_app, full_db_conn, branch_id):
        req_id, items, admin, token = self._approved_requirement(full_app, full_db_conn, branch_id, qty=4.0)
        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        kitchen.post(f"/kitchen/review/{req_id}/request-edit", data={"_csrf_token": ktoken, "reason": "store short on stock"})
        edit_id = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementEdit WHERE requirementId = ? ORDER BY createdAt DESC LIMIT 1", (req_id,)
        ).fetchone()["id"]

        resp = kitchen.post(f"/kitchen/review/{req_id}/edit/submit", data={
            "_csrf_token": ktoken, "editId": edit_id,
            "itemId": [items[0]["id"]], "qty": ["2"], "reason": [""],
        }, follow_redirects=True)
        assert b"Enter a reason for changing" in resp.data
        assert items[0]["name"].encode() in resp.data
        status = full_db_conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (req_id,)).fetchone()["status"]
        assert status == "APPROVED", "rejected edit must not revert status"

    def test_full_edit_flow_reverts_to_pending_and_records_change(self, full_app, full_db_conn, branch_id):
        req_id, items, admin, token = self._approved_requirement(full_app, full_db_conn, branch_id, qty=4.0)
        before_issues = full_db_conn.execute("SELECT COUNT(*) c FROM StockIssue").fetchone()["c"]

        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        kitchen.post(f"/kitchen/review/{req_id}/request-edit", data={"_csrf_token": ktoken, "reason": "store short on stock"})
        edit_id = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementEdit WHERE requirementId = ? ORDER BY createdAt DESC LIMIT 1", (req_id,)
        ).fetchone()["id"]

        resp = kitchen.post(f"/kitchen/review/{req_id}/edit/submit", data={
            "_csrf_token": ktoken, "editId": edit_id,
            "itemId": [items[0]["id"]], "qty": ["2"], "reason": ["only 2kg physically available"],
        }, follow_redirects=True)
        assert b"pending admin approval again" in resp.data

        row = full_db_conn.execute("SELECT status FROM KitchenRequirement WHERE id = ?", (req_id,)).fetchone()
        assert row["status"] == "PENDING"

        item_row = full_db_conn.execute(
            "SELECT qty FROM KitchenRequirementItem WHERE requirementId = ? AND matchedItemId = ?",
            (req_id, items[0]["id"]),
        ).fetchone()
        assert item_row["qty"] == 2.0

        change = full_db_conn.execute(
            "SELECT action, previousQty, newQty, reason FROM KitchenRequirementItemChange WHERE editId = ?", (edit_id,)
        ).fetchone()
        assert change["action"] == "UPDATE"
        assert change["previousQty"] == 4.0
        assert change["newQty"] == 2.0
        assert change["reason"] == "only 2kg physically available"

        after_issues = full_db_conn.execute("SELECT COUNT(*) c FROM StockIssue").fetchone()["c"]
        assert after_issues == before_issues, "no stock movement until re-approved and re-issued"

        # Re-approve + issue -- the EDITED qty (2kg), not the original 4kg,
        # is what should flow into the actual StockIssueItem.
        _approve(admin, token, req_id, branch_id)
        _issue(admin, token, req_id, branch_id)
        issued_qty = full_db_conn.execute(
            "SELECT sii.qty FROM StockIssueItem sii JOIN StockIssue si ON si.id = sii.stockIssueId "
            "WHERE si.sourceRequirementId = ?", (req_id,)
        ).fetchone()
        assert issued_qty["qty"] == 2.0

    def test_unchanged_items_need_no_reason(self, full_app, full_db_conn, branch_id):
        """Only lines whose qty actually differs need a reason -- an
        untouched item in the same edit submission is a no-op."""
        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items = full_db_conn.execute("SELECT id, name FROM Item WHERE active = 1 LIMIT 2").fetchall()
        dept = full_db_conn.execute("SELECT id FROM Department WHERE active = 1 LIMIT 1").fetchone()
        req_id = _submit(admin, token, branch_id, dept["id"], "REGULAR",
                          [{"itemId": items[0]["id"], "qty": 4}, {"itemId": items[1]["id"], "qty": 3}])
        _approve(admin, token, req_id, branch_id)

        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        kitchen.post(f"/kitchen/review/{req_id}/request-edit", data={"_csrf_token": ktoken, "reason": "adjust one item"})
        edit_id = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementEdit WHERE requirementId = ? ORDER BY createdAt DESC LIMIT 1", (req_id,)
        ).fetchone()["id"]

        resp = kitchen.post(f"/kitchen/review/{req_id}/edit/submit", data={
            "_csrf_token": ktoken, "editId": edit_id,
            "itemId": [items[0]["id"], items[1]["id"]], "qty": ["4", "1"],
            "reason": ["", "ran low"],  # first item unchanged (still 4) -- no reason given, and none required
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"pending admin approval again" in resp.data

        changes = full_db_conn.execute(
            "SELECT itemLabel FROM KitchenRequirementItemChange WHERE editId = ?", (edit_id,)
        ).fetchall()
        assert len(changes) == 1, "only the actually-changed item gets a change record"

    def test_edit_can_remove_an_item_with_reason(self, full_app, full_db_conn, branch_id):
        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items, dept = _two_items_and_dept(full_db_conn)
        req_id = _submit(admin, token, branch_id, dept["id"], "REGULAR", [{"itemId": items[0]["id"], "qty": 4}])
        _approve(admin, token, req_id, branch_id)

        kitchen = _kitchen_client(full_app, full_db_conn, branch_id)
        ktoken = csrf_token(kitchen)
        kitchen.post(f"/kitchen/review/{req_id}/request-edit", data={"_csrf_token": ktoken, "reason": "don't need this anymore"})
        edit_id = full_db_conn.execute(
            "SELECT id FROM KitchenRequirementEdit WHERE requirementId = ? ORDER BY createdAt DESC LIMIT 1", (req_id,)
        ).fetchone()["id"]

        kitchen.post(f"/kitchen/review/{req_id}/edit/submit", data={
            "_csrf_token": ktoken, "editId": edit_id,
            "itemId": [items[0]["id"]], "qty": ["0"], "reason": ["not needed today"],
        })
        remaining = full_db_conn.execute(
            "SELECT COUNT(*) c FROM KitchenRequirementItem WHERE requirementId = ?", (req_id,)
        ).fetchone()["c"]
        assert remaining == 0
        change = full_db_conn.execute(
            "SELECT action FROM KitchenRequirementItemChange WHERE editId = ?", (edit_id,)
        ).fetchone()
        assert change["action"] == "DELETE"


class TestNavBadgeCounts:
    def test_pending_and_approved_counts_track_each_transition(self, full_app, full_db_conn, branch_id):
        from app.services.kitchen_requirement import get_approved_requirements, get_pending_requirements

        admin = _admin_client(full_app, full_db_conn)
        token = csrf_token(admin)
        items, dept = _two_items_and_dept(full_db_conn)
        admin_row = full_db_conn.execute(
            "SELECT id, role, branchId FROM User WHERE role = 'ADMIN' ORDER BY createdAt DESC LIMIT 1"
        ).fetchone()
        admin_user = dict(admin_row)

        before_pending = len(get_pending_requirements(full_db_conn, admin_user))
        before_approved = len(get_approved_requirements(full_db_conn, admin_user))

        req_id = _submit(admin, token, branch_id, dept["id"], "REGULAR", [{"itemId": items[0]["id"], "qty": 4}])
        assert len(get_pending_requirements(full_db_conn, admin_user)) == before_pending + 1
        assert len(get_approved_requirements(full_db_conn, admin_user)) == before_approved

        _approve(admin, token, req_id, branch_id)
        assert len(get_pending_requirements(full_db_conn, admin_user)) == before_pending
        assert len(get_approved_requirements(full_db_conn, admin_user)) == before_approved + 1

        _issue(admin, token, req_id, branch_id)
        assert len(get_pending_requirements(full_db_conn, admin_user)) == before_pending
        assert len(get_approved_requirements(full_db_conn, admin_user)) == before_approved
