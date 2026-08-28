"""Generic WSGI entry point (e.g. for waitress or gunicorn)."""
from app import create_app

application = create_app()
