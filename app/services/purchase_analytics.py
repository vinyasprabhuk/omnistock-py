"""
Port of src/lib/inventory/purchaseAnalytics.ts.

All spend analytics are computed by fetching PurchaseItem rows (joined with
Purchase + Item) and aggregating in Python loops -- spend is qty * rate, a
per-row product that's simplest to compute this way, and dataset sizes here
(a single restaurant's purchase history) are small (~750 rows).

Purchases have no department field (only Stock Issues do) -- a single
purchase/invoice usually restocks several departments, so "spend by
department" is ESTIMATED: each item's average purchase rate applied to how
much of that item was issued to each department. Only covers items both
purchased and issued.

DEVIATION FROM THE LIVE APP (user-approved): the original TypeScript's
get_spend_by_department has a bug where a department-name filter silently
drops the branch filter (two object spreads onto the same `stockIssue` key,
the second overwriting the first). This port applies both filters together,
since that's clearly the intended behavior and the bug only matters once a
second branch is added.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TypedDict

from app.dates import from_db, parse_date_key, today_key
from app.services.spend_periods import PeriodComparison, compute_period_comparison

_UTC = timezone.utc
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class DateRange(TypedDict, total=False):
    from_: datetime | None  # 'from' is a Python keyword; use from_ in code, map at call sites
    to: datetime | None


class PurchaseItemRow(TypedDict):
    qty: float
    rate: float
    date: datetime
    branchId: str
    branchName: str
    supplier: str | None
    itemId: str
    itemName: str
    unit: str


def fetch_all_rows(conn: sqlite3.Connection, branch_id: str | None = None) -> list[PurchaseItemRow]:
    conditions = []
    params: list = []
    if branch_id:
        conditions.append("p.branchId = ?")
        params.append(branch_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        "SELECT pi.qty AS qty, pi.rate AS rate, p.date AS date, p.branchId AS branchId, "
        "b.name AS branchName, p.supplier AS supplier, pi.itemId AS itemId, "
        "i.name AS itemName, i.unit AS unit "
        "FROM PurchaseItem pi "
        "JOIN Purchase p ON p.id = pi.purchaseId "
        "JOIN Branch b ON b.id = p.branchId "
        "JOIN Item i ON i.id = pi.itemId "
        f"{where} ORDER BY p.date ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "qty": float(r["qty"]), "rate": float(r["rate"]), "date": from_db(r["date"]),
            "branchId": r["branchId"], "branchName": r["branchName"], "supplier": r["supplier"],
            "itemId": r["itemId"], "itemName": r["itemName"], "unit": r["unit"],
        }
        for r in rows
    ]


def in_range(date: datetime, range_: dict | None) -> bool:
    if range_ is None:
        return True
    frm = range_.get("from")
    to = range_.get("to")
    if frm and date < frm:
        return False
    if to and date > to:
        return False
    return True


def month_key(d: datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(mk: str) -> str:
    year, month = mk.split("-")
    return f"{_MONTH_ABBR[int(month) - 1]} {year}"


def _prev_month_key(today: datetime) -> str:
    if today.month == 1:
        return f"{today.year - 1:04d}-12"
    return f"{today.year:04d}-{today.month - 1:02d}"


class SpendSummary(TypedDict):
    totalSpend: float
    spendThisMonth: float
    spendPreviousMonth: float
    spendChangePercent: float | None
    avgUnitPrice: float


def get_purchase_period_comparison(conn: sqlite3.Connection, branch_id: str | None = None) -> PeriodComparison:
    rows = fetch_all_rows(conn, branch_id)
    return compute_period_comparison([{"date": r["date"], "spend": r["qty"] * r["rate"]} for r in rows])


def get_spend_summary(conn: sqlite3.Connection, branch_id: str | None = None,
                       range_: dict | None = None) -> SpendSummary:
    rows = fetch_all_rows(conn, branch_id)
    today = parse_date_key(today_key())
    this_month_key = month_key(today)
    prev_month_key = _prev_month_key(today)

    total_spend = 0.0
    total_qty = 0.0
    spend_this_month = 0.0
    spend_prev_month = 0.0

    for r in rows:
        spend = r["qty"] * r["rate"]
        k = month_key(r["date"])
        if k == this_month_key:
            spend_this_month += spend
        if k == prev_month_key:
            spend_prev_month += spend
        if in_range(r["date"], range_):
            total_spend += spend
            total_qty += r["qty"]

    spend_change_percent = (
        ((spend_this_month - spend_prev_month) / spend_prev_month) * 100 if spend_prev_month > 0 else None
    )

    return {
        "totalSpend": total_spend, "spendThisMonth": spend_this_month,
        "spendPreviousMonth": spend_prev_month, "spendChangePercent": spend_change_percent,
        "avgUnitPrice": total_spend / total_qty if total_qty > 0 else 0.0,
    }


class IngredientSpendRow(TypedDict):
    itemId: str
    itemName: str
    unit: str
    totalQty: float
    totalSpend: float
    avgRate: float
    latestRate: float | None
    previousRate: float | None
    changePercent: float | None


def get_spend_by_ingredient(conn: sqlite3.Connection, branch_id: str | None = None,
                             range_: dict | None = None) -> list[IngredientSpendRow]:
    rows = [r for r in fetch_all_rows(conn, branch_id) if in_range(r["date"], range_)]
    by_item: dict[str, dict] = {}
    for r in rows:
        entry = by_item.setdefault(r["itemId"], {
            "itemName": r["itemName"], "unit": r["unit"], "totalQty": 0.0, "totalSpend": 0.0, "entries": [],
        })
        entry["totalQty"] += r["qty"]
        entry["totalSpend"] += r["qty"] * r["rate"]
        entry["entries"].append({"date": r["date"], "rate": r["rate"]})

    result = []
    for item_id, v in by_item.items():
        entries = sorted(v["entries"], key=lambda e: e["date"])
        latest_rate = entries[-1]["rate"] if entries else None
        previous_rate = entries[-2]["rate"] if len(entries) > 1 else None
        change_percent = (
            ((latest_rate - previous_rate) / previous_rate) * 100
            if previous_rate is not None and previous_rate > 0 else None
        )
        result.append({
            "itemId": item_id, "itemName": v["itemName"], "unit": v["unit"],
            "totalQty": v["totalQty"], "totalSpend": v["totalSpend"],
            "avgRate": v["totalSpend"] / v["totalQty"] if v["totalQty"] > 0 else 0.0,
            "latestRate": latest_rate, "previousRate": previous_rate, "changePercent": change_percent,
        })
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class DepartmentSpendRow(TypedDict):
    department: str
    totalSpend: float


def get_spend_by_department(conn: sqlite3.Connection, branch_id: str | None = None,
                             range_: dict | None = None,
                             department_name: str | None = None) -> list[DepartmentSpendRow]:
    rows = [r for r in fetch_all_rows(conn, branch_id) if in_range(r["date"], range_)]
    qty_by_item: dict[str, float] = {}
    spend_by_item: dict[str, float] = {}
    for r in rows:
        qty_by_item[r["itemId"]] = qty_by_item.get(r["itemId"], 0.0) + r["qty"]
        spend_by_item[r["itemId"]] = spend_by_item.get(r["itemId"], 0.0) + r["qty"] * r["rate"]
    avg_rate_by_item = {
        item_id: total_spend / (qty_by_item.get(item_id) or 1)
        for item_id, total_spend in spend_by_item.items()
    }

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
        "SELECT si.itemId AS itemId, si.qty AS qty, s.date AS date, d.name AS departmentName "
        "FROM StockIssueItem si "
        "JOIN StockIssue s ON s.id = si.stockIssueId "
        "JOIN Department d ON d.id = s.departmentId "
        f"{where}"
    )
    issued_rows = conn.execute(sql, params).fetchall()

    by_department: dict[str, float] = {}
    for i in issued_rows:
        issue_date = from_db(i["date"])
        if not in_range(issue_date, range_):
            continue
        avg_rate = avg_rate_by_item.get(i["itemId"])
        if avg_rate is None:
            continue  # never purchased (in range) -- no rate to estimate spend with
        key = i["departmentName"]
        by_department[key] = by_department.get(key, 0.0) + float(i["qty"]) * avg_rate

    result = [{"department": k, "totalSpend": v} for k, v in by_department.items()]
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class SupplierSpendRow(TypedDict):
    supplier: str
    totalSpend: float


def get_spend_by_supplier(conn: sqlite3.Connection, branch_id: str | None = None,
                           range_: dict | None = None) -> list[SupplierSpendRow]:
    rows = [r for r in fetch_all_rows(conn, branch_id) if in_range(r["date"], range_)]
    by_supplier: dict[str, float] = {}
    for r in rows:
        key = (r["supplier"] or "").strip() or "No supplier recorded"
        by_supplier[key] = by_supplier.get(key, 0.0) + r["qty"] * r["rate"]
    result = [{"supplier": k, "totalSpend": v} for k, v in by_supplier.items()]
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class BranchSpendRow(TypedDict):
    branchId: str
    branchName: str
    totalSpend: float


def get_spend_by_branch(conn: sqlite3.Connection, range_: dict | None = None) -> list[BranchSpendRow]:
    """Always all-branch -- a per-branch breakdown is meaningless scoped to one branch already."""
    rows = [r for r in fetch_all_rows(conn, None) if in_range(r["date"], range_)]
    by_branch: dict[str, dict] = {}
    for r in rows:
        entry = by_branch.setdefault(r["branchId"], {"branchName": r["branchName"], "totalSpend": 0.0})
        entry["totalSpend"] += r["qty"] * r["rate"]
    result = [{"branchId": k, "branchName": v["branchName"], "totalSpend": v["totalSpend"]}
              for k, v in by_branch.items()]
    return sorted(result, key=lambda r: r["totalSpend"], reverse=True)


class MonthSpendRow(TypedDict):
    monthKey: str
    monthLabel: str
    totalSpend: float


def get_spend_by_month(conn: sqlite3.Connection, branch_id: str | None = None,
                        range_: dict | None = None, months: int = 12) -> list[MonthSpendRow]:
    rows = [r for r in fetch_all_rows(conn, branch_id) if in_range(r["date"], range_)]
    by_month: dict[str, float] = {}
    for r in rows:
        k = month_key(r["date"])
        by_month[k] = by_month.get(k, 0.0) + r["qty"] * r["rate"]
    sorted_rows = sorted(
        ({"monthKey": mk, "monthLabel": month_label(mk), "totalSpend": v} for mk, v in by_month.items()),
        key=lambda r: r["monthKey"],
    )
    return sorted_rows[-months:] if months > 0 else sorted_rows
