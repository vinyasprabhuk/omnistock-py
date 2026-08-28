"""
One-time password migration for the two accounts found in the live DB:
  - admin: rehash to a new real password (replaces the temporary "admin123").
  - kitchen@example.com: deactivate (unused seed/test account), per the
    user's explicit decision at planning time -- not rehashed at all.

Run against the working copy first (instance/dev.db, the default), verify,
then re-run with --db pointed at the real server DB at actual cutover.

Usage:
  python3 tools/migrate_admin_password.py                     # interactive
  python3 tools/migrate_admin_password.py --db path/to/dev.db
"""
from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "instance" / "dev.db"))
    parser.add_argument("--password", help="Skip the interactive prompt (for scripted/test use only).")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    admin = conn.execute("SELECT id, email, role FROM User WHERE email = 'admin'").fetchone()
    if admin is None:
        print("No 'admin' user found -- nothing to migrate.")
    else:
        password = args.password
        if not password:
            print(f"Setting a new password for admin account (db: {db_path})")
            password = getpass.getpass("New admin password (min 8 chars): ")
            confirm = getpass.getpass("Confirm: ")
            if password != confirm:
                print("Passwords did not match. Aborting.")
                return 1
        if len(password) < 8:
            print("Password must be at least 8 characters.")
            return 1

        new_hash = hash_password(password)
        conn.execute("UPDATE User SET passwordHash = ? WHERE id = ?", (new_hash, admin["id"]))
        print(f"Updated password for '{admin['email']}' (role={admin['role']}).")

    kitchen = conn.execute(
        "SELECT id, email, active FROM User WHERE email = 'kitchen@example.com'"
    ).fetchone()
    if kitchen is None:
        print("No 'kitchen@example.com' account found -- nothing to deactivate.")
    elif not kitchen["active"]:
        print("'kitchen@example.com' is already inactive.")
    else:
        conn.execute("UPDATE User SET active = 0 WHERE id = ?", (kitchen["id"],))
        print("Deactivated 'kitchen@example.com' (unused seed/test account).")

    conn.commit()
    conn.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
