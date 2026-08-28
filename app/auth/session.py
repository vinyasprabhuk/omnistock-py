"""
Port of src/lib/auth/session.ts.

resolveBranchScope is THE single enforcement point used by every write
action: a non-admin's session branch always wins, regardless of what a
request claims. ADMIN must pass an explicit branch id.
"""
from __future__ import annotations


class ForbiddenError(Exception):
    pass


class UnauthorizedError(Exception):
    pass


def resolve_branch_scope(user: dict, requested_branch_id: str | None) -> str:
    role = user["role"]
    branch_id = user.get("branchId")

    if role == "ADMIN":
        if not requested_branch_id:
            raise ForbiddenError("branchId is required for ADMIN requests")
        return requested_branch_id

    if not branch_id:
        raise ForbiddenError("User has no assigned branch")
    if requested_branch_id and requested_branch_id != branch_id:
        raise ForbiddenError("Cannot access another branch's data")
    return branch_id
