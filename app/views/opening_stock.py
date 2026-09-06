from __future__ import annotations

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from app.auth.page_branch import list_branches_for_admin, page_resolve_branch
from app.security import require_write
from app.services.match_item import match_item
from app.services.opening_stock import get_items_with_opening_stock, set_opening_stock_qty

bp = Blueprint("opening_stock", __name__)


@bp.route("/opening-stock", methods=["GET"])
def index():
    conn = g.conn
    branch_param = request.args.get("branchId")
    branch = page_resolve_branch(conn, g.user, branch_param)
    is_admin = g.user["role"] == "ADMIN"
    branches = list_branches_for_admin(conn) if is_admin else []

    items = get_items_with_opening_stock(conn, branch["branchId"])
    return render_template(
        "opening_stock/index.html", branch=branch, is_admin=is_admin,
        branches=branches, items=items,
    )


@bp.route("/opening-stock/<item_id>/save", methods=["POST"])
@require_write
def save(item_id: str):
    conn = g.conn
    user_branch_id = g.user.get("branchId")
    branch_id = user_branch_id or request.form.get("branchId")
    qty_raw = request.form.get("qty")

    if not branch_id:
        return jsonify({"error": "Select a branch first"}), 400
    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a valid quantity"}), 400

    try:
        set_opening_stock_qty(conn, item_id, branch_id, qty)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "itemId": item_id, "qty": qty})
    return redirect(url_for("opening_stock.index", branchId=branch_id))


@bp.route("/opening-stock/voice-match", methods=["POST"])
@require_write
def voice_match():
    """Takes {"text": "<spoken item name>"} (transcribed client-side via
    the Web Speech API -- no audio ever reaches the server, just the
    already-recognized text) and matches it against Item Master,
    reusing the exact same fuzzy/alias matcher as Excel imports."""
    conn = g.conn
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No speech text provided"}), 400

    result = match_item(conn, text)
    return jsonify(result)
