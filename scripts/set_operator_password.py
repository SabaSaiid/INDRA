#!/usr/bin/env python3
"""
Set operator passwords: a bcrypt hash in user_profiles.password_hash.

Accounts live in the database (migration 0019). No password is in the source
and none is seeded, so an account cannot sign in until this script gives it one.

    python scripts/set_operator_password.py commander          # prompts twice
    python scripts/set_operator_password.py --all --generate   # a new password each, printed once
    python scripts/set_operator_password.py --all --from-env INDRA_OPERATOR_PASSWORD

It writes to DATABASE_URL from the environment, else the one in backend/.env
or the repo-root .env (the backend's own settings), and prints the host, port
and database before it changes anything. A username with no row in
user_profiles is refused with exit status 2: accounts are not created here.
So is a password shorter than 10 characters.

Run it from the repo root with the backend's virtualenv.
"""

import argparse
import asyncio
import getpass
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

MIN_PASSWORD_LENGTH = 10
# token_urlsafe(18) is 24 characters, 144 random bits.
GENERATED_BYTES = 18


class Refused(Exception):
    """A request this script will not carry out; exit status 2."""


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set operator passwords (bcrypt) in user_profiles.password_hash."
    )
    parser.add_argument("usernames", nargs="*", metavar="USERNAME", help="accounts to set")
    parser.add_argument("--all", action="store_true", help="every account in user_profiles")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--from-env", metavar="VAR", help="use the password in this environment variable for every account"
    )
    source.add_argument(
        "--generate", action="store_true", help="generate a password per account and print each once"
    )
    args = parser.parse_args(argv)
    if not args.usernames and not args.all:
        parser.error("name at least one USERNAME, or pass --all")
    if args.usernames and args.all:
        parser.error("name USERNAMEs or pass --all, not both")
    return args


def password_problem(password: str) -> str:
    """Why this password must not be used, or "" if it will do."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"shorter than {MIN_PASSWORD_LENGTH} characters"
    return ""


def unknown_usernames(requested, known) -> list:
    """The requested names with no row in user_profiles, in the order given."""
    known = set(known)
    return [name for name in requested if name not in known]


def describe_target(url: str) -> str:
    """host:port/database. Never the credentials in the URL."""
    from sqlalchemy.engine import make_url

    u = make_url(url)
    return f"{u.host}:{u.port or 5432}/{u.database}"


def choose_passwords(usernames, args, environ, prompt=getpass.getpass) -> dict:
    """username → password, from the environment, generated, or typed twice."""
    if args.from_env:
        password = environ.get(args.from_env, "")
        if not password:
            raise Refused(f"{args.from_env} is not set, or is empty")
        problem = password_problem(password)
        if problem:
            raise Refused(f"the password in {args.from_env} is {problem}")
        return {name: password for name in usernames}

    if args.generate:
        return {name: secrets.token_urlsafe(GENERATED_BYTES) for name in usernames}

    chosen = {}
    for name in usernames:
        first = prompt(f"New password for {name}: ")
        problem = password_problem(first)
        if problem:
            raise Refused(f"the password for {name} is {problem}")
        if prompt(f"Repeat the password for {name}: ") != first:
            raise Refused(f"the two passwords typed for {name} differ")
        chosen[name] = first
    return chosen


async def _known_usernames(engine) -> list:
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT username FROM user_profiles ORDER BY username"))
        return [r[0] for r in rows]


async def _write_hashes(engine, hashes: dict) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        for name, password_hash in hashes.items():
            await conn.execute(
                text("UPDATE user_profiles SET password_hash = :h WHERE username = :u"),
                {"h": password_hash, "u": name},
            )


async def run(args, environ) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings
    from app.core.security import hash_password

    url = get_settings().DATABASE_URL
    print(f"Database: {describe_target(url)}")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        try:
            known = await _known_usernames(engine)
        except Exception as e:
            print(f"Could not read user_profiles: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

        if args.all:
            usernames = known
            if not usernames:
                raise Refused("user_profiles has no accounts")
        else:
            usernames = list(dict.fromkeys(args.usernames))
            missing = unknown_usernames(usernames, known)
            if missing:
                raise Refused(
                    f"no account named {', '.join(missing)} in user_profiles "
                    f"(accounts: {', '.join(known) or 'none'})"
                )

        passwords = choose_passwords(usernames, args, environ)
        hashes = {name: hash_password(pw) for name, pw in passwords.items()}
        try:
            await _write_hashes(engine, hashes)
        except Exception as e:
            print(
                f"Could not write the hashes: {type(e).__name__}: {e}\n"
                "Has migration 0019 run? (cd backend && alembic upgrade head)",
                file=sys.stderr,
            )
            return 1
    finally:
        await engine.dispose()

    for name in usernames:
        if args.generate:
            print(f"  {name}: {passwords[name]}")
        else:
            print(f"  {name}: password set")
    if args.generate:
        print("Each generated password is shown once, here. Store them now.")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args, os.environ))
    except Refused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
