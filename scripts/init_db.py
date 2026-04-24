from __future__ import annotations

import sys

from backend.app.config import settings
from backend.app.database import get_db_connection, init_tables
from backend.app.services.auth import hash_password


def seed_admin() -> None:
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM admin WHERE username = ?",
            (settings.admin_username,),
        ).fetchone()
        if existing is not None:
            print(f"Admin '{settings.admin_username}' already exists; skipping.")
            return
        conn.execute(
            "INSERT INTO admin (username, hashed_password) VALUES (?, ?)",
            (settings.admin_username, hash_password(settings.admin_password)),
        )
        print(f"Admin '{settings.admin_username}' created.")


def main() -> int:
    init_tables()
    print(f"Schema initialized at {settings.db_path_resolved}")
    seed_admin()
    return 0


if __name__ == "__main__":
    sys.exit(main())
