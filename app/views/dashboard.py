"""Port of src/app/(app)/dashboard/page.tsx -- the most complex page in the app."""
from __future__ import annotations

from flask import Blueprint, g, render_template, request

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, from_db, today_key
from app.services import purchase_analytics as pa
from app.services import usage_analytics as ua
from app.services.calculations import get_low_stock, get_master_inventory, get_period_tracker
from app.services.spend_periods import get_period_boundaries

bp = Blueprint("dashboard", __name__)


def _sum_qty(conn, table: str, join_table: str, join_col: str, branch_id: str,
             date_eq=None, date_gte=None, date_lte=None) -> float:
    conditions = ["j.branchId = ?"]
    params: list = [branch_id]
    if date_eq is not None:
        conditions.append("j.date = ?"); params.append(date_eq)
    if date_gte is not None:
        conditions.append("j.date >= ?"); params.append(date_gte)
    if date_lte is not None:
        conditions.append("j.date <= ?"); params.append(date_lte)
    sql = (
        f"SELECT COALESCE(SUM(t.qty), 0) FROM {table} t "
        f"JOIN {join_table} j ON j.id = t.{join_col} WHERE {' AND '.join(conditions)}"
    )
    return float(conn.execute(sql, params).fetchone()[0] or 0)


def _sum_purchase_spend(conn, branch_id: str, date_eq=None, date_gte=None, date_lte=None) -> float:
    conditions = ["j.branchId = ?"]
    params: list = [branch_id]
    if date_eq is not None:
        conditions.append("j.date = ?"); params.append(date_eq)
    if date_gte is not None:
        conditions.append("j.date >= ?"); params.append(date_gte)
    if date_lte is not None:
        conditions.append("j.date <= ?"); params.append(date_lte)
    sql = (
        "SELECT COALESCE(SUM(t.qty * t.rate), 0) FROM PurchaseItem t "
        f"JOIN Purchase j ON j.id = t.purchaseId WHERE {' AND '.join(conditions)}"
    )
    return float(conn.execute(sql, params).fetchone()[0] or 0)


def _sum_issue_spend(conn, branch_id: str, avg_rate_by_item: dict[str, float],
                      date_eq=None, date_gte=None, date_lte=None) -> float:
    """StockIssueItem has no rate of its own, so (mirroring usage_analytics'
    convention) each item's all-history average purchase rate values it."""
    conditions = ["j.branchId = ?"]
    params: list = [branch_id]
    if date_eq is not None:
        conditions.append("j.date = ?"); params.append(date_eq)
    if date_gte is not None:
        conditions.append("j.date >= ?"); params.append(date_gte)
    if date_lte is not None:
        conditions.append("j.date <= ?"); params.append(date_lte)
    sql = (
        "SELECT t.itemId AS itemId, t.qty AS qty FROM StockIssueItem t "
        f"JOIN StockIssue j ON j.id = t.stockIssueId WHERE {' AND '.join(conditions)}"
    )
    rows = conn.execute(sql, params).fetchall()
    return sum(float(r["qty"]) * avg_rate_by_item.get(r["itemId"], 0.0) for r in rows)


@bp.route("/dashboard")
def index():
    conn = g.conn
    args = request.args

    branch_param = args.get("branchId")
    from_param = args.get("from") or None
    to_param = args.get("to") or None
    department_param = args.get("department") or None
    cmp_mode_param = args.get("cmpMode")
    cmp_a_from, cmp_a_to = args.get("cmpAFrom") or None, args.get("cmpATo") or None
    cmp_b_from, cmp_b_to = args.get("cmpBFrom") or None, args.get("cmpBTo") or None
    cmp_item_ids_raw = args.getlist("cmpItems")
    cmp_dept_param = args.get("cmpDept") or None
    active_tab = args.get("tab") or "comparison"

    branch = page_resolve_branch(conn, g.user, branch_param)
    branch_id = branch["branchId"]
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(conn) if is_admin else []

    today = today_key()
    range_from_db = date_key_to_db(from_param) if from_param else None
    range_to_db = date_key_to_db(to_param) if to_param else None
    range_ = {"from": from_db(range_from_db) if range_from_db else None,
              "to": from_db(range_to_db) if range_to_db else None}
    department_name = department_param if department_param and department_param != "all" else ""
    is_filtered = bool(from_param or to_param)

    # date filter for consolidated requirement / today's purchases+issued
    req_date_eq = req_date_gte = req_date_lte = None
    if is_filtered:
        req_date_gte, req_date_lte = range_from_db, range_to_db
    else:
        req_date_eq = date_key_to_db(today)

    # --- comparison-tab period setup ---
    if cmp_a_from or cmp_a_to or cmp_b_from or cmp_b_to:
        cmp_mode = "custom"
    elif cmp_mode_param == "month":
        cmp_mode = "month"
    elif cmp_mode_param == "custom":
        cmp_mode = "custom"
    else:
        cmp_mode = "week"

    bounds = get_period_boundaries()
    if cmp_mode == "month":
        period_a = {"from": bounds["lastMonthStart"], "to": bounds["lastMonthEnd"], "label": "Last Month"}
        period_b = {"from": bounds["thisMonthStart"], "to": bounds["thisMonthEnd"], "label": "This Month"}
    elif cmp_mode == "custom":
        period_a = {"from": from_db(date_key_to_db(cmp_a_from)) if cmp_a_from else bounds["lastWeekStart"],
                    "to": from_db(date_key_to_db(cmp_a_to)) if cmp_a_to else bounds["lastWeekEnd"], "label": "Period A"}
        period_b = {"from": from_db(date_key_to_db(cmp_b_from)) if cmp_b_from else bounds["thisWeekStart"],
                    "to": from_db(date_key_to_db(cmp_b_to)) if cmp_b_to else bounds["thisWeekEnd"], "label": "Period B"}
    else:
        period_a = {"from": bounds["lastWeekStart"], "to": bounds["lastWeekEnd"], "label": "Last Week"}
        period_b = {"from": bounds["thisWeekStart"], "to": bounds["thisWeekEnd"], "label": "This Week"}

    cmp_item_ids = [i for i in cmp_item_ids_raw if i]
    cmp_dept = cmp_dept_param or ""
    cmp_range_start = min(period_a["from"], period_b["from"])
    cmp_range_end = max(period_a["to"], period_b["to"])

    # --- fetch everything (mirrors the original's Promise.all -- always computed regardless of active tab) ---
    from app.dates import to_db as _to_db
    inventory = get_master_inventory(conn, branch_id, range_to_db)
    today_purchase_spend = _sum_purchase_spend(conn, branch_id, req_date_eq, req_date_gte, req_date_lte)
    avg_rate_by_item = ua.get_avg_rate_by_item(conn)
    today_issue_spend = _sum_issue_spend(conn, branch_id, avg_rate_by_item, req_date_eq, req_date_gte, req_date_lte)

    spend_summary = pa.get_spend_summary(conn, branch_id, range_)
    spend_by_ingredient = pa.get_spend_by_ingredient(conn, branch_id, range_)
    spend_by_department = pa.get_spend_by_department(conn, branch_id, range_, department_name)
    spend_by_supplier = pa.get_spend_by_supplier(conn, branch_id, range_)
    spend_by_month = pa.get_spend_by_month(conn, branch_id, range_)
    spend_by_branch = pa.get_spend_by_branch(conn, range_) if is_admin else []
    purchase_period = pa.get_purchase_period_comparison(conn, branch_id)

    departments = [r["name"] for r in conn.execute("SELECT name FROM Department WHERE active = 1 ORDER BY name ASC")]

    usage_summary = ua.get_usage_summary(conn, branch_id, range_, department_name)
    usage_by_ingredient = ua.get_usage_by_ingredient(conn, branch_id, range_, department_name)
    usage_by_department = ua.get_usage_by_department(conn, branch_id, range_, department_name)
    usage_by_month = ua.get_usage_by_month(conn, branch_id, range_, department_name=department_name)
    usage_by_branch = ua.get_usage_by_branch(conn, range_) if is_admin else []
    usage_period = ua.get_usage_period_comparison(conn, branch_id, department_name)

    tracker_a = get_period_tracker(conn, branch_id, _to_db(period_a["from"]), _to_db(period_a["to"]))
    tracker_b = get_period_tracker(conn, branch_id, _to_db(period_b["from"]), _to_db(period_b["to"]))
    all_items = [dict(r) for r in conn.execute("SELECT id, name FROM Item WHERE active = 1 ORDER BY name ASC")]

    cmp_dept_item_ids = None
    if cmp_dept:
        rows = conn.execute(
            "SELECT DISTINCT si.itemId FROM StockIssueItem si JOIN StockIssue s ON s.id = si.stockIssueId "
            "JOIN Department d ON d.id = s.departmentId "
            "WHERE s.branchId = ? AND d.name = ? AND s.date >= ? AND s.date <= ?",
            (branch_id, cmp_dept, _to_db(cmp_range_start), _to_db(cmp_range_end)),
        ).fetchall()
        cmp_dept_item_ids = {r["itemId"] for r in rows}

    # --- period comparison rows ---
    tracker_a_by_id = {r["itemId"]: r for r in tracker_a}
    tracker_compare_rows = []
    for b in tracker_b:
        a = tracker_a_by_id.get(b["itemId"])
        if a is None:
            a = {**b, "opening": 0, "purchased": 0, "kitchenRequirement": 0, "issued": 0, "closing": 0, "usageCost": 0}
        tracker_compare_rows.append({"a": a, "b": b})
    tracker_compare_rows = [
        r for r in tracker_compare_rows
        if (r["a"]["purchased"] or r["a"]["issued"] or r["b"]["purchased"] or r["b"]["issued"] or r["a"]["opening"] or r["b"]["opening"])
        and (not cmp_item_ids or r["b"]["itemId"] in cmp_item_ids)
        and (cmp_dept_item_ids is None or r["b"]["itemId"] in cmp_dept_item_ids)
    ]
    # NOTE: the original's sort comparator `(x,y) => y.b.usageCost - x.a.usageCost`
    # mixes period A/B fields (almost certainly an unintentional bug -- every
    # other sort in this file compares like-for-like). Sorting by period B's
    # usage cost descending (the evident intent) instead.
    tracker_compare_rows.sort(key=lambda r: r["b"]["usageCost"], reverse=True)

    low_stock = get_low_stock(conn, branch_id, range_to_db)
    total_store_value = sum(r["storeValue"] for r in inventory)
    breakdown_total = today_purchase_spend + today_issue_spend + total_store_value
    breakdown_pct = {
        "purchase": (today_purchase_spend / breakdown_total * 100) if breakdown_total else 0.0,
        "issue": (today_issue_spend / breakdown_total * 100) if breakdown_total else 0.0,
        "inventory": (total_store_value / breakdown_total * 100) if breakdown_total else 0.0,
    }
    max_month_spend = max([1] + [m["totalSpend"] for m in spend_by_month])
    max_department_spend = max([1] + [d["totalSpend"] for d in spend_by_department])
    max_usage_month = max([1] + [m["totalSpend"] for m in usage_by_month])
    max_usage_department = max([1] + [d["totalSpend"] for d in usage_by_department])
    usage_department_total = sum(d["totalSpend"] for d in usage_by_department)

    return render_template(
        "dashboard/index.html",
        branch=branch, is_admin=is_admin, branches=branches, active_tab=active_tab,
        from_param=from_param or "", to_param=to_param or "", department_name=department_name,
        departments=departments, is_filtered=is_filtered,
        today_purchase_spend=today_purchase_spend,
        today_issue_spend=today_issue_spend, total_store_value=total_store_value,
        breakdown_pct=breakdown_pct,
        period_a=period_a, period_b=period_b, cmp_mode=cmp_mode,
        cmp_a_from=cmp_a_from or "", cmp_a_to=cmp_a_to or "", cmp_b_from=cmp_b_from or "", cmp_b_to=cmp_b_to or "",
        all_items=all_items, cmp_item_ids=cmp_item_ids, cmp_dept=cmp_dept,
        tracker_compare_rows=tracker_compare_rows,
        spend_summary=spend_summary, spend_by_ingredient=spend_by_ingredient,
        spend_by_department=spend_by_department, spend_by_supplier=spend_by_supplier,
        spend_by_month=spend_by_month, spend_by_branch=spend_by_branch,
        purchase_period=purchase_period, max_month_spend=max_month_spend, max_department_spend=max_department_spend,
        usage_summary=usage_summary, usage_by_ingredient=usage_by_ingredient,
        usage_by_department=usage_by_department, usage_by_month=usage_by_month,
        usage_by_branch=usage_by_branch, usage_period=usage_period,
        max_usage_month=max_usage_month, max_usage_department=max_usage_department,
        usage_department_total=usage_department_total,
        low_stock=low_stock,
    )
