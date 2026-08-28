"""
Port of src/lib/inventory/usageAnalytics.ts.

"Usage spend" (consumption spend) estimates the cost of what was actually
ISSUED to departments -- Stock Issue quantity x the item's average purchase
rate -- as opposed to Purchase spend (money spent buying stock). The rate
basis is always each item's OVERALL average purchase rate (all history, NOT
range-filtered) so period-over-period usage comparisons reflect quantity
trends, not price swings mixed in. This is an intentional asymmetry with
get_spend_by_department (which now uses a range-filtered rate basis after
the deliberate bug fix there) -- keep both as genuinely different rate bases.

DEVIATION FROM THE LIVE APP (user-requested): the original never threads the
dashboard's department filter into any usage-spend function at all -- only
Purchase Spend's "Spend by Department" breakdown responded to it. Every
usage function here now accepts an optional department_name filter so
picking a department on the Dashboard actually scopes Usage Spend too.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TypedDict

from app.dates import from_db, parse_date_key, today_key
from app.services.purchase_analytics import in_range, month_key, month_label, _prev_month_key
from app.services.spend_periods import PeriodComparison, compute_period_comparison


def get_avg_rate_by_item(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute("SELECT itemId, qty, rate FROM PurchaseItem").fetchall()
    spend: dict[str, float] = {}
    qty: dict[str, float] = {}
    for r in rows:
        q = float(r["qty"])
        spend[r["itemId"]] = spend.get(r["itemId"], 0.0) + q * float(r["rate"])
        qty[r["itemId"]] = qty.get(r["itemId"], 0.0) + q
    return {item_id: total_spend / (qty.get(item_id) or 1) for item_id, total_spend in spend.items()}


class UsageRow(TypedDict):
    qty: float
    spend: float
    date: datetime
    branchId: str
    branchName: str
    departmentName: str
    itemId: str
    itemName: str
    unit: str


def fetch_usage_rows(conn: sqlite3.Connection, branch_id: str | None = None,
                      department_name: str | None = None) -> list[UsageRow]:
    avg_rate_by_item = get_avg_rate_by_item(conn)

    conditions = []
    params: list = []
    if branch_id:
        conditions.append("s.branchId = ?")
        params.append(branch_id)
    if department_name and department_name != "all":
        conditions.append("d.name = ?")
        params.append(department_name)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        "SELECT si.itemId AS itemId, si.qty AS qty, s.date AS date, s.branchId AS branchId, "
        "b.name AS branchName, d.name AS departmentName, i.name AS itemName, i.unit AS unit "
        "FROM StockIssueItem si "
        "JOIN StockIssue s ON s.id = si.stockIssueId "
        "JOIN Branch b ON b.id = s.branchId "
        "JOIN Department d ON d.id = s.departmentId "
        "JOIN Item i ON i.id = si.itemId "
        f"{where} ORDER BY s.date ASC"
    )
    rows = conn.execute(sql, params).fetchall()

    result: list[UsageRow] = []
    for r in rows:
        avg_rate = avg_rate_by_item.get(r["itemId"])
        if avg_rate is None:
            continue  # never purchased -- no rate to estimate cost with
        qty = float(r["qty"])
        result.append({
            "qty": qty, "spend": qty * avg_rate, "date": from_db(r["date"]),
            "branchId": r["branchId"], "branchName": r["branchName"],
            "departmentName": r["departmentName"], "itemId": r["itemId"],
            "itemName": r["itemName"], "unit": r["unit"],
        })
    return result


class UsageSummary(TypedDict):
    totalSpend: float
    spendThisMonth: float
    spendPreviousMonth: float
    spendChangePercent: float | None


def get_usage_summary(conn: sqlite3.Connection, branch_id: str | None = None,
                       range_: dict | None = None, department_name: str | None = None) -> UsageSummary:
    rows = fetch_usage_rows(conn, branch_id, department_name)
    today = parse_date_key(today_key())
    this_month_key = month_key(today)
    prev_month_key = _prev_month_key(today)

    total_spend = 0.0
    spend_this_month = 0.0
    spend_prev_month = 0.0
    for r in rows:
        k = month_key(r["date"])
        if k == this_month_key:
            spend_this_month += r["spend"]
        if k == prev_month_key:
            spend_prev_month += r["spend"]
        if in_range(r["date"], range_):
            total_spend += r["spend"]

    return {
        "totalSpend": total_spend, "spendThisMonth": spend_this_month,
        "spendPreviousMonth": spend_prev_month,
        "spendChangePercent": (
            ((spend_this_month - spend_prev_month) / spend_prev_month) * 100 if spend_prev_month > 0 else None
        ),
    }


def get_usage_period_comparison(conn: sqlite3.Connection, branch_id: str | None = None,
                                 department_name: str | None = None) -> PeriodComparison:
    rows = fetch_usage_rows(conn, branch_id, department_name)
    return compute_period_comparison([{"date": r["date"], "spend": r["spend"]} for r in rows])


class UsageIngredientRow(TypedDict):
    itemId: str
    itemName: str
    unit: str
    totalQty: float
    totalSpend: float


def get_usage_by_ingredient(conn: sqlite3.Connection, branch_id: str | None = None,
                             range_: dict | None = None, department_name: str | None = None) -> list[UsageIngredientRow]:
    rows = [r for r in fetch_usage_rows(conn, branch_id, department_name) if in_range(r["date"], range_)]
    by_item: dict[str, dict] = {}
    for r in rows:
        entry = by_item.setdefault(r["itemId"], {"itemName": r["itemName"], "unit": r["unit"],
                                                    "totalQty": 0.0, "totalSpend": 0.0})
        entry["totalQty"] += r["qty"]
        entry["totalSpend"] += r["spend"]
    result = [{"itemId": k, **v} for k, v in by_item.items()]
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class UsageDepartmentRow(TypedDict):
    department: str
    totalSpend: float


def get_usage_by_department(conn: sqlite3.Connection, branch_id: str | None = None,
                             range_: dict | None = None, department_name: str | None = None) -> list[UsageDepartmentRow]:
    rows = [r for r in fetch_usage_rows(conn, branch_id, department_name) if in_range(r["date"], range_)]
    by_dept: dict[str, float] = {}
    for r in rows:
        by_dept[r["departmentName"]] = by_dept.get(r["departmentName"], 0.0) + r["spend"]
    result = [{"department": k, "totalSpend": v} for k, v in by_dept.items()]
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class UsageBranchRow(TypedDict):
    branchId: str
    branchName: str
    totalSpend: float


def get_usage_by_branch(conn: sqlite3.Connection, range_: dict | None = None) -> list[UsageBranchRow]:
    rows = [r for r in fetch_usage_rows(conn, None) if in_range(r["date"], range_)]
    by_branch: dict[str, dict] = {}
    for r in rows:
        entry = by_branch.setdefault(r["branchId"], {"branchName": r["branchName"], "totalSpend": 0.0})
        entry["totalSpend"] += r["spend"]
    result = [{"branchId": k, "branchName": v["branchName"], "totalSpend": v["totalSpend"]}
              for k, v in by_branch.items()]
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class UsageMonthRow(TypedDict):
    monthKey: str
    monthLabel: str
    totalSpend: float


def get_usage_by_month(conn: sqlite3.Connection, branch_id: str | None = None,
                        range_: dict | None = None, months: int = 12,
                        department_name: str | None = None) -> list[UsageMonthRow]:
    rows = [r for r in fetch_usage_rows(conn, branch_id, department_name) if in_range(r["date"], range_)]
    by_month: dict[str, float] = {}
    for r in rows:
        k = month_key(r["date"])
        by_month[k] = by_month.get(k, 0.0) + r["spend"]
    sorted_rows = sorted(
        ({"monthKey": mk, "monthLabel": month_label(mk), "totalSpend": v} for mk, v in by_month.items()),
        key=lambda r: r["monthKey"],
    )
    return sorted_rows[-months:] if months > 0 else sorted_rows
