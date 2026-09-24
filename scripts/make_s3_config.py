#!/usr/bin/env python3
"""
Write infra/seaweedfs/s3.json, the object store's identity file, from .env.

SeaweedFS's S3 gateway reads its access keys from a JSON file rather than from
environment variables, and docker-compose.yml mounts that file read-only into
the `objectstore` container. The keys are secrets, so the file is gitignored and
generated here from the same S3_ACCESS_KEY / S3_SECRET_KEY the backend uses:
one source of truth, and the two can never disagree.

    python scripts/make_s3_config.py            # write it (refuses to overwrite)
    python scripts/make_s3_config.py --force    # replace an existing one

Run it before the first `docker compose up`. If the file is missing when the
container starts, Docker creates an empty *directory* at that path instead, and
the gateway will not start until it is removed and the file generated.

Values are read from the environment first, then from the repo-root `.env`, the
same order the backend's settings use.
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"
OUT = REPO_ROOT / "infra" / "seaweedfs" / "s3.json"

# The identity the backend signs as. "Admin" lets it create the buckets at
# startup; the gateway listens on 127.0.0.1 only, so nothing else can reach it.
IDENTITY_NAME = "indra-backend"
ACTIONS = ["Admin", "Read", "List", "Tagging", "Write"]


def read_env_file(path: Path) -> dict:
    """KEY=VALUE lines, ignoring comments and blanks; quotes around a value are stripped."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="overwrite an existing s3.json")
    args = parser.parse_args()

    file_values = read_env_file(ENV_FILE)
    access = os.environ.get("S3_ACCESS_KEY") or file_values.get("S3_ACCESS_KEY", "")
    secret = os.environ.get("S3_SECRET_KEY") or file_values.get("S3_SECRET_KEY", "")

    if not access or not secret:
        print(
            "S3_ACCESS_KEY and S3_SECRET_KEY must both be set in .env first.\n"
            "Generate them with:\n"
            "  openssl rand -hex 12   # access key\n"
            "  openssl rand -hex 32   # secret key",
            file=sys.stderr,
        )
        return 1
    if "change-me" in access or "change-me" in secret:
        print("S3 keys still hold the .env.example placeholders; generate real ones.", file=sys.stderr)
        return 1

    if OUT.is_dir():
        # What Docker leaves behind when the container started before this ran.
        print(
            f"{OUT} is a directory (Docker created it because the file was missing).\n"
            f"Stop the container, remove it with `rmdir {OUT}`, and run this again.",
            file=sys.stderr,
        )
        return 1
    if OUT.exists() and not args.force:
        print(f"{OUT} already exists; pass --force to replace it.", file=sys.stderr)
        return 1

    config = {
        "identities": [
            {
                "name": IDENTITY_NAME,
                "credentials": [{"accessKey": access, "secretKey": secret}],
                "actions": ACTIONS,
            }
        ]
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    # Readable by others on purpose, not 0600: the gateway inside the container
    # may run as a different uid from the host user who owns the file, and an
    # unreadable identity file stops the S3 API from starting. The file sits in
    # a gitignored path on a single-user server, which is where the secrecy is.
    OUT.chmod(0o644)
    print(f"Wrote {OUT.relative_to(REPO_ROOT)} for identity {IDENTITY_NAME!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
