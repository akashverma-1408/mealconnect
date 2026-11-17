"""Command-line helpers.

Admins cannot sign up through the API, so the first admin is created from the terminal:

    python -m app.cli create-admin --email admin@example.com --name "Platform Admin"

The password is asked for interactively (never pass passwords as command arguments:
they end up in your shell history).
"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.schemas.auth import RegisterRequest
from app.services.auth_service import get_user_by_email


def create_admin(email: str, name: str) -> int:
    password = getpass.getpass("Admin password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:  # reuse the API's validation rules for email, name and password strength
        data = RegisterRequest(email=email, password=password, full_name=name)
    except ValidationError as exc:
        for err in exc.errors():
            print(f"{err['loc'][0]}: {err['msg']}", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        if get_user_by_email(db, data.email):
            print(f"A user with email {data.email} already exists.", file=sys.stderr)
            return 1
        admin = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.ADMIN,
        )
        db.add(admin)
        db.commit()
        print(f"Admin created: id={admin.id} email={admin.email}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Create an administrator account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
