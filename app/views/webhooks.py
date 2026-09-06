"""
Public-but-localhost-only endpoints for external services running on
this same machine to push data in. Registered under PUBLIC_PATHS
(app/__init__.py) so it skips the normal login/CSRF gate entirely --
its own guard here is "the request must originate from localhost"
instead, since the sending service has no user session to authenticate
with. Never add a route here that a browser session should be able to
call -- that belongs in an ordinary blueprint.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.services.purchase_webhook import ingest_purchase_invoice_webhook

bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

_LOCALHOST_ADDRS = ("127.0.0.1", "::1")


@bp.route("/purchase-invoice", methods=["POST"])
def purchase_invoice():
    # ProxyFix (see app/__init__.py's create_app) already resolves
    # remote_addr to the real client IP from X-Forwarded-For, so this
    # correctly rejects anything that didn't originate on this machine
    # even though every request physically arrives via the Apache/
    # Passenger reverse proxy.
    if request.remote_addr not in _LOCALHOST_ADDRS:
        return jsonify({"error": "This endpoint only accepts local requests"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object body"}), 400

    try:
        event_id = ingest_purchase_invoice_webhook(g.conn, payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"status": "received", "eventId": event_id}), 201
