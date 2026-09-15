"""Port of src/app/(app)/dashboard/page.tsx -- the most complex page in the app."""
from __future__ import annotations

import sqlite3

from flask import Blueprint, g, render_template, request

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.dates import date_key_to_db, from_db, parse_date_key, shift_date_key, today_key
from app.services import purchase_analytics as pa
from app.services import usage_analytics as ua
from app.services.calculations import get_low_stock, get_master_inventory, get_period_tracker
from app.services.spend_periods import get_period_boundaries
from app.services.wastage_variance import get_production_wastage_variance_trend

_CHART_TREND_WIDTH = 720
_CHART_TREND_HEIGHT = 180
_CHART_MAX_DAYS = 60

_DEPT_COLOR_PALETTE = [
    "#315bff", "#c02626", "#178a3c", "#92400e", "#7c3aed", "#0891b2",
    "#db2777", "#65a30d", "#ea580c", "#4338ca", "#0d9488", "#a16207",
]


def _chart_day_range(from_param: str | None, to_param: str | None, today: str) -> tuple[str, str]:
    """Resolves the day-range charts (Spend/Usage/Production-Wastage by
    day) aggregate over: the dashboard's own date filter when set
    (capped so a huge filtered range can't blow up the per-day
    Production/Wastage matcher loop), else today only -- the "Today" /
    "Last Week" quick-picks and the plain From/To fields all set the
    same from/to query params, so this is the one place that decides
    what an unset filter defaults to."""
    if from_param and to_param:
        from_key, to_key = from_param, to_param
    else:
        from_key = to_key = today
    if (parse_date_key(to_key) - parse_date_key(from_key)).days > _CHART_MAX_DAYS:
        from_key = shift_date_key(to_key, -_CHART_MAX_DAYS)
    return from_key, to_key


def _fill_missing_days(rows: list[dict], from_key: str, to_key: str, value_key: str) -> list[dict]:
    """Reindexes a sparse {dayKey, dayLabel, <value_key>} list (only
    days with actual activity) onto every calendar day in the range, so
    a bar chart shows one bar per day, not just the days with data."""
    by_key = {r["dayKey"]: r for r in rows}
    filled = []
    key = from_key
    while key <= to_key:
        if key in by_key:
            filled.append(by_key[key])
        else:
            filled.append({"dayKey": key, "dayLabel": pa.day_label(key), value_key: 0.0})
        key = shift_date_key(key, 1)
    return filled


def _trend_svg_points(rows: list[dict], value_key: str, min_value: float, max_value: float) -> str:
    """Maps values onto the chart's y-axis using a shared min/max across
    all series (not just this one), so Produced/Wasted/Variance stay on
    the same scale and remain comparable -- Variance can go negative
    (more sold than produced+wasted, e.g. drawing down existing stock),
    so this can't assume a 0 floor the way a plain bar chart could."""
    n = len(rows)
    if n == 0:
        return ""
    span = max_value - min_value
    x_step = _CHART_TREND_WIDTH / (n - 1) if n > 1 else 0.0
    points = []
    for i, r in enumerate(rows):
        x = i * x_step
        y = (_CHART_TREND_HEIGHT - ((r[value_key] - min_value) / span * _CHART_TREND_HEIGHT)) if span else _CHART_TREND_HEIGHT / 2
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def _department_spend_trend(conn, branch_id: str, chart_range: dict, department_name: str | None,
                             from_key: str, to_key: str) -> dict:
    """One line per department, day by day, over the chart's date range
    -- same Usage-spend basis (StockIssueItem qty x each item's all-time
    average purchase rate) as the existing Usage by Department bars,
    just broken out per calendar day instead of summed over the whole
    range. Honors the dashboard's department filter (narrows to one
    line rather than dropping the chart)."""
    rows = ua.get_usage_by_day_and_department(conn, branch_id, chart_range, department_name)
    departments = sorted({r["department"] for r in rows})
    by_key = {(r["dayKey"], r["department"]): r["totalSpend"] for r in rows}

    day_keys = []
    key = from_key
    while key <= to_key:
        day_keys.append(key)
        key = shift_date_key(key, 1)

    tooltip_days = [{"dayLabel": pa.day_label(dk), "values": {}} for dk in day_keys]
    series = []
    max_value = 1.0
    for i, dept in enumerate(departments):
        dept_rows = [{"dayKey": dk, "totalSpend": by_key.get((dk, dept), 0.0)} for dk in day_keys]
        max_value = max(max_value, max(r["totalSpend"] for r in dept_rows))
        for day_row, tt in zip(dept_rows, tooltip_days):
            tt["values"][dept] = round(day_row["totalSpend"], 2)
        series.append({"department": dept, "color": _DEPT_COLOR_PALETTE[i % len(_DEPT_COLOR_PALETTE)],
                        "rows": dept_rows})

    for s in series:
        s["points"] = _trend_svg_points(s["rows"], "totalSpend", 0.0, max_value)
        del s["rows"]

    has_data = any(v for tt in tooltip_days for v in tt["values"].values())
    return {
        "series": series,
        "day_labels": [pa.day_label(dk) for dk in day_keys],
        "tooltip_days": tooltip_days,
        "has_data": has_data,
        "label_step": 1 if len(day_keys) <= 14 else 3,
    }

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

    # --- quick date-range picks for the Purchase/Usage/Trend day-wise charts
    # (and the shared From/To filter, since they write the same params) ---
    last_week_from_key = bounds["lastWeekStart"].strftime("%Y-%m-%d")
    last_week_to_key = bounds["lastWeekEnd"].strftime("%Y-%m-%d")
    this_month_from_key = bounds["thisMonthStart"].strftime("%Y-%m-%d")
    this_month_to_key = bounds["thisMonthEnd"].strftime("%Y-%m-%d")
    last_month_from_key = bounds["lastMonthStart"].strftime("%Y-%m-%d")
    last_month_to_key = bounds["lastMonthEnd"].strftime("%Y-%m-%d")
    last_7_days_from_key = shift_date_key(today, -6)
    last_7_days_to_key = today

    is_today_preset = not from_param and not to_param
    is_last_week_preset = from_param == last_week_from_key and to_param == last_week_to_key
    is_this_month_preset = from_param == this_month_from_key and to_param == this_month_to_key
    is_last_month_preset = from_param == last_month_from_key and to_param == last_month_to_key
    is_last_7_days_preset = from_param == last_7_days_from_key and to_param == last_7_days_to_key

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

    # --- date-wise chart data (Spend by Day, Usage by Day, Production vs Wastage trend) ---
    chart_from_key, chart_to_key = _chart_day_range(from_param, to_param, today)
    chart_range = {"from": parse_date_key(chart_from_key), "to": parse_date_key(chart_to_key)}
    spend_by_day = _fill_missing_days(
        pa.get_spend_by_day(conn, branch_id, chart_range), chart_from_key, chart_to_key, "totalSpend")
    usage_by_day = _fill_missing_days(
        ua.get_usage_by_day(conn, branch_id, chart_range, department_name), chart_from_key, chart_to_key, "totalSpend")
    max_spend_day = max([1.0] + [d["totalSpend"] for d in spend_by_day])
    max_usage_day = max([1.0] + [d["totalSpend"] for d in usage_by_day])

    try:
        trend_rows = get_production_wastage_variance_trend(conn, branch_id, chart_from_key, chart_to_key)
    except sqlite3.OperationalError:
        # Recipe/DishSale (added by migrate_add_intent_recipe) aren't on
        # every DB this view might run against -- e.g. the pristine
        # parity-test snapshot predates that migration. Degrade to an
        # empty trend rather than 500ing the whole Dashboard over one tab.
        trend_rows = []
    trend_values = [v for r in trend_rows for v in (r["produced"], r["wasted"], r["variance"])]
    trend_max = max([0.0] + trend_values)
    trend_min = min([0.0] + trend_values)
    trend_produced_points = _trend_svg_points(trend_rows, "produced", trend_min, trend_max)
    trend_wasted_points = _trend_svg_points(trend_rows, "wasted", trend_min, trend_max)
    trend_variance_points = _trend_svg_points(trend_rows, "variance", trend_min, trend_max)
    trend_zero_y = _CHART_TREND_HEIGHT - ((0 - trend_min) / (trend_max - trend_min) * _CHART_TREND_HEIGHT) if trend_max > trend_min else _CHART_TREND_HEIGHT / 2
    trend_has_data = any(r["produced"] or r["wasted"] or r["sold"] for r in trend_rows)
    trend_any_sales = any(r["salesAvailable"] for r in trend_rows)

    dept_trend = _department_spend_trend(conn, branch_id, chart_range, department_name, chart_from_key, chart_to_key)

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
        spend_by_day=spend_by_day, max_spend_day=max_spend_day,
        usage_by_day=usage_by_day, max_usage_day=max_usage_day,
        trend_rows=trend_rows, trend_has_data=trend_has_data, trend_any_sales=trend_any_sales,
        trend_produced_points=trend_produced_points, trend_wasted_points=trend_wasted_points,
        trend_variance_points=trend_variance_points, trend_zero_y=trend_zero_y,
        trend_width=_CHART_TREND_WIDTH, trend_height=_CHART_TREND_HEIGHT,
        dept_trend=dept_trend,
        today_key=today, last_week_from_key=last_week_from_key, last_week_to_key=last_week_to_key,
        this_month_from_key=this_month_from_key, this_month_to_key=this_month_to_key,
        last_month_from_key=last_month_from_key, last_month_to_key=last_month_to_key,
        last_7_days_from_key=last_7_days_from_key, last_7_days_to_key=last_7_days_to_key,
        is_today_preset=is_today_preset, is_last_week_preset=is_last_week_preset,
        is_this_month_preset=is_this_month_preset, is_last_month_preset=is_last_month_preset,
        is_last_7_days_preset=is_last_7_days_preset,
    )
