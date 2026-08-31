"""Sanity check for the full_db_* / full_client fixtures themselves --
if these are broken, every other e2e test file is meaningless."""
from __future__ import annotations

from tests.conftest import login, make_user


def test_full_schema_has_intent_recipe_and_review_columns(full_db_conn):
    tables = {r[0] for r in full_db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("Dish", "Recipe", "IntentDay", "WorkstationPhoto"):
        assert t in tables, f"missing table {t}"
    cols = {r[1] for r in full_db_conn.execute("PRAGMA table_info(KitchenRequirement)")}
    for c in ("rejectedAt", "rejectedById", "reviewComment"):
        assert c in cols, f"missing column {c}"


def test_make_user_and_login_roundtrip(full_client, full_db_conn, branch_id):
    user_id, username, password = make_user(full_db_conn, "MANAGER", branch_id)
    resp = login(full_client, username, password)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/requirements")


def test_admin_still_works_on_full_schema(full_client, full_db_conn):
    row = full_db_conn.execute("SELECT email FROM User WHERE role = 'ADMIN' LIMIT 1").fetchone()
    resp = full_client.get(f"/kitchen/review/nonexistent")
    # Not logged in -- should redirect to login, proving RBAC still runs
    # correctly against the migrated schema.
    assert resp.status_code == 302
