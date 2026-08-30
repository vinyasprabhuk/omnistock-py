"""
Authenticated/public file-serving routes -- mirrors the Next.js app's
/api/{production,wastage}/photo/[id], /api/purchases/receipt/[id], and the
/branding/* static-asset exemption in src/proxy.ts's PUBLIC_PATHS.

Photo/receipt routes are added in the wastage/production/purchases phases;
this file starts with just the branding logo, which must be public (it's
shown on the pre-login page).
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, abort, g, send_from_directory

from app.auth.session import ForbiddenError, resolve_branch_scope
from app.services import storage

bp = Blueprint("files", __name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@bp.route("/branding/<path:filename>")
def branding_asset(filename: str):
    return send_from_directory(STATIC_DIR / "branding", filename)


@bp.route("/api/purchases/receipt/<purchase_id>")
def purchase_receipt(purchase_id: str):
    row = g.conn.execute(
        "SELECT branchId, receiptPath, receiptMimeType FROM Purchase WHERE id = ?", (purchase_id,)
    ).fetchone()
    if row is None or not row["receiptPath"]:
        abort(404)
    try:
        resolve_branch_scope(g.user, row["branchId"])
    except ForbiddenError:
        abort(403)
    data = storage.read(row["receiptPath"])
    return Response(data, mimetype=row["receiptMimeType"] or "application/octet-stream")


def _serve_log_photo(table: str, entry_id: str):
    row = g.conn.execute(
        f"SELECT branchId, photoPath, photoMimeType FROM {table} WHERE id = ?", (entry_id,)
    ).fetchone()
    if row is None or not row["photoPath"]:
        abort(404)
    try:
        resolve_branch_scope(g.user, row["branchId"])
    except ForbiddenError:
        abort(403)
    data = storage.read(row["photoPath"])
    return Response(data, mimetype=row["photoMimeType"] or "image/jpeg")


@bp.route("/api/wastage/photo/<entry_id>")
def wastage_photo(entry_id: str):
    return _serve_log_photo("Wastage", entry_id)


@bp.route("/api/production/photo/<entry_id>")
def production_photo(entry_id: str):
    return _serve_log_photo("ProductionLog", entry_id)


@bp.route("/api/workstation/photo/<entry_id>")
def workstation_photo(entry_id: str):
    return _serve_log_photo("WorkstationPhoto", entry_id)
