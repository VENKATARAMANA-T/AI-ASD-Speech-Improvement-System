"""Create (or reset the password of) a doctor account.

    .venv\\Scripts\\python.exe scripts\\create_doctor.py "Dr. Priya" priya@clinic.org
    .venv\\Scripts\\python.exe scripts\\create_doctor.py "Dr. Priya" priya@clinic.org --password s3cret

Without ``--password`` the password is prompted for. An existing email gets
its name and password replaced, so this also serves as a password reset; the
doctor's existing sign-ins stop working. Connects to DATABASE_URL.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.portal.db import db_session, init_db, now_iso  # noqa: E402
from src.portal.security import hash_password, password_problem  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("email")
    ap.add_argument("--password", help="prompted for if omitted")
    args = ap.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if (why := password_problem(password)):
        print(why, file=sys.stderr)
        return 2

    init_db()
    with db_session() as conn:
        existing = conn.execute("SELECT id FROM doctors WHERE email = %s", (args.email,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE doctors SET name = %s, password_hash = %s, token_version = token_version + 1 WHERE id = %s",
                (args.name, hash_password(password), existing["id"]),
            )
            print(f"Updated doctor {args.email}")
        else:
            conn.execute("INSERT INTO doctors (name, email, password_hash, created_at) VALUES (%s, %s, %s, %s)",
                         (args.name, args.email, hash_password(password), now_iso()))
            print(f"Created doctor {args.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
