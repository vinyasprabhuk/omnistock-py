"""Role-based route access -- positive (role that should reach a page
does) and negative (role that shouldn't gets redirected away, never a
raw 500). Sourced directly from app.auth.permissions.ROUTE_ACCESS
(the actual code this suite is testing against, assuming the checked-out
commit here matches what's deployed) rather than a hand-duplicated
mapping that could silently drift out of sync."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.auth.permissions import ROUTE_ACCESS  # noqa: E402

from conftest import ROLE_CREDS, login_as, require_role  # noqa: E402

ALL_ROLES = ["ADMIN", "KITCHEN", "STORE", "MANAGER", "VIEWER", "DEPTLEAD"]
ROLE_NAME_IN_APP = {  # this suite's env-var role names -> the app's actual role string
    "ADMIN": "ADMIN", "KITCHEN": "KITCHEN", "STORE": "STORE",
    "MANAGER": "MANAGER", "VIEWER": "VIEWER", "DEPTLEAD": "DEPARTMENT_LEAD",
}


@pytest.mark.parametrize("prefix,allowed_roles", ROUTE_ACCESS)
@pytest.mark.parametrize("role", ALL_ROLES)
def test_route_access_matches_permissions_table(page, ui_base_url, role, prefix, allowed_roles):
    creds = ROLE_CREDS.get(role)
    if creds is None:
        pytest.skip(f"UI_TEST_{role}_USER/PASS not set")
    user, pw = creds
    login_as(page, ui_base_url, user, pw)

    resp = page.goto(f"{ui_base_url}{prefix}")
    should_have_access = ROLE_NAME_IN_APP[role] in allowed_roles

    assert resp.status < 500, f"{role} hitting {prefix} produced a server error"
    if should_have_access:
        assert prefix in page.url, f"{role} should reach {prefix} but was redirected to {page.url}"
    else:
        assert prefix not in page.url or page.url.rstrip("/").endswith(prefix) is False, \
            f"{role} should NOT reach {prefix} but landed on {page.url}"
