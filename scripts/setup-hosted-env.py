#!/usr/bin/env python3
"""Store your Neon and Upstash connection strings in backend/.env.neon (git-ignored).

Run:  python3 scripts/setup-hosted-env.py

Both values are typed/pasted with HIDDEN input, so they never appear on screen, in your
shell history or in chat. The file is created with permissions 600 (only you can read it).
It does NOT touch backend/.env (your local-development settings).
"""

import getpass
import os
import secrets
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "backend" / ".env.neon"


def clean_database_url(raw: str) -> str:
    raw = raw.strip().strip("'\"")
    if raw.startswith("psql "):  # Neon's "psql 'postgresql://...'" snippet
        raw = raw[5:].strip().strip("'\"")
    if not raw.startswith(("postgresql://", "postgres://")):
        sys.exit("That does not look like a Neon connection string (should start with postgresql://).")
    if "@" not in raw or "sslmode" not in raw:
        sys.exit("The Neon string should contain a password (user:pass@host) and ?sslmode=require.")
    return raw


def clean_redis_url(raw: str) -> str:
    raw = raw.strip().strip("'\"")
    i = raw.find("redis://") if "rediss://" not in raw else raw.find("rediss://")
    if i < 0:
        # Not a URL: assume only the PASSWORD/token was copied (Upstash Details page).
        if not raw or " " in raw or "/" in raw or "@" in raw:
            sys.exit("That is not an Upstash password or URL. Copy the line starting redis-cli --tls -u redis://")
        host = input("Paste the Upstash ENDPOINT (looks like xxx-1234.upstash.io), Enter: ").strip()
        host = host.removeprefix("rediss://").removeprefix("redis://").split(":")[0].strip("/")
        if not host.endswith(".upstash.io"):
            sys.exit("The endpoint should end with .upstash.io")
        return f"rediss://default:{raw}@{host}:6379"
    url = raw[i:].split()[0]
    if url.startswith("redis://"):
        url = "rediss://" + url[len("redis://") :]  # Upstash only accepts TLS connections
    return url


def main() -> None:
    if TARGET.exists() and input(f"{TARGET.name} exists. Overwrite? [y/N] ").lower() != "y":
        sys.exit("Left it unchanged.")
    db = clean_database_url(getpass.getpass("Paste the Neon connection string (hidden), Enter: "))
    rd = clean_redis_url(getpass.getpass("Paste the Upstash connection text (hidden), Enter: "))
    lines = [
        # single quotes: URLs contain & and ? which the shell would otherwise interpret
        f"DATABASE_URL='{db}'",
        f"REDIS_URL='{rd}'",
        # Throw-away secrets for local runs against the hosted services (Render makes its own).
        f"JWT_SECRET_KEY={secrets.token_hex(32)}",
        f"PAYMENT_WEBHOOK_SECRET={secrets.token_hex(32)}",
        "ENVIRONMENT=development",  # lets the seed script run; production is set on Render
        "",
    ]
    fd = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))
    print(f"Saved {TARGET} (permissions 600). Nothing was printed or sent anywhere.")


if __name__ == "__main__":
    main()
