import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_or_create_secret_key() -> str:
    """
    Production hosting (Passenger) typically runs several worker PROCESSES
    behind one app. A key generated fresh in each process's memory (e.g. via
    secrets.token_hex() at import time) would differ between workers, so a
    session cookie signed by one worker fails to validate on the next request
    if it lands on a different worker -- intermittent, hard-to-reproduce
    "login doesn't work in prod" symptoms that are fine in local dev (single
    process) but break exactly the way logins broke on the old Next.js
    deployment. The key must be stable across processes and restarts, so it's
    read from SECRET_KEY if set, else persisted to a local file and reused.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    key_file = BASE_DIR / "instance" / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()

    key = secrets.token_hex(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


class Config:
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "instance" / "dev.db"))
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads"))
    SECRET_KEY = _load_or_create_secret_key()
    # Override "today" for reproducible local testing (see app/dates.py). Format: YYYY-MM-DD.
    APP_TODAY = os.environ.get("APP_TODAY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set automatically by ProxyFix below when the request came in over HTTPS
    # (Passenger/Apache terminate TLS and proxy to the app over plain HTTP).
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
