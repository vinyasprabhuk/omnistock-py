"""
PWA support -- makes the site installable to a phone's home screen (Android:
a real installable app via the browser's "Install app" prompt; iOS: "Add to
Home Screen" using the apple-touch-icon). manifest.json is generated
dynamically so it always reflects the current branding (app name, theme
color) rather than going stale when an admin changes those settings.
"""
from __future__ import annotations

from flask import Blueprint, Response, g, jsonify

from app.services.branding import get_branding

bp = Blueprint("pwa", __name__)


@bp.route("/manifest.json")
def manifest():
    branding = get_branding(g.conn)
    theme_color = branding.get("headerColor") or "#0b1f44"
    return jsonify({
        "name": branding["appName"],
        "short_name": branding["appName"][:12],
        "description": branding.get("tagline") or "Restaurant inventory management",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#f5f7fb",
        "theme_color": theme_color,
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    })


@bp.route("/sw.js")
def service_worker():
    # Deliberately minimal: no offline caching (this app is data-live, not a
    # good candidate for offline use -- stock numbers must always be current).
    # A registered service worker with a fetch handler is still what most
    # browsers/PWA-packaging tools (e.g. PWABuilder) require to consider the
    # site "installable" at all -- this satisfies that without pretending to
    # support offline use.
    js = """
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
"""
    return Response(js, mimetype="application/javascript")
