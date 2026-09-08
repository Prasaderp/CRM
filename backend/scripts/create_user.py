from __future__ import annotations

import argparse
import getpass
import hmac
from collections.abc import Sequence

from pydantic import PostgresDsn

from real_estate_crm.auth.service import AuthService, DuplicateUser, PasswordPolicyError
from real_estate_crm.config import get_settings
from real_estate_crm.db import get_session_factory


def _target(dsn: PostgresDsn) -> tuple[str, str]:
    """Return the (host, database) this command would write to.

    `PostgresDsn` is a multi-host URL, so the host lives in `hosts()` rather than
    a `host` attribute. The operator reads this before confirming, so it has to
    name the real server.
    """
    hosts = [str(entry.get("host")) for entry in dsn.hosts() if entry.get("host")]
    database = (dsn.path or "").lstrip("/")
    if not database:
        raise ValueError("database_url does not name a database")
    return ", ".join(hosts) or "unknown-host", database


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create one CRM user")
    parser.add_argument("email")
    parser.add_argument("display_name")
    parser.add_argument("role", choices=("admin", "agent"))
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        host, database = _target(settings.database_url)
    except ValueError as exc:
        parser.error(str(exc))

    # The database name must be typed back. This is the only guard against
    # creating an account in the wrong environment, so it is never skipped.
    print(f"Creating a {args.role} user in database '{database}' on host '{host}'.")
    if input(f"Type the database name to continue [{database}]: ").strip() != database:
        parser.error("database name did not match; no user was created")

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not hmac.compare_digest(password, confirmation):
        parser.error("password confirmation does not match")

    try:
        user = AuthService(get_session_factory()).create_user(
            args.email, args.display_name, password, args.role
        )
    except (DuplicateUser, PasswordPolicyError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Created {user.role} user {user.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
