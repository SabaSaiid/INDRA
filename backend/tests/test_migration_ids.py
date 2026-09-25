"""
Every Alembic revision ID must fit in `alembic_version.version_num`.

Alembic creates that column as varchar(32). A longer ID is accepted by every
file-level check and fails only at the end of the upgrade, when Alembic writes
the new head: `value too long for type character varying(32)`. Postgres rolls
the whole migration back, so nothing is damaged, but the deploy stops there.
Phase 2's `0015_feed_status_and_placeless_reports` (38 characters) did exactly
that on its first run against a scratch database.
"""

import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
VERSION_NUM_WIDTH = 32

# Both `revision = "…"` and the annotated `revision: str = "…"` forms occur.
_REVISION = re.compile(r'^revision\b[^=\n]*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_DOWN_REVISION = re.compile(r'^down_revision\b[^=\n]*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def _revisions() -> dict[str, str]:
    found = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        match = _REVISION.search(path.read_text())
        if match:
            found[path.name] = match.group(1)
    return found


def test_every_revision_id_fits_the_version_column():
    too_long = {
        name: rev for name, rev in _revisions().items() if len(rev) > VERSION_NUM_WIDTH
    }
    assert not too_long, f"revision IDs longer than {VERSION_NUM_WIDTH}: {too_long}"


def test_every_down_revision_names_an_existing_revision():
    known = set(_revisions().values())
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        match = _DOWN_REVISION.search(path.read_text())
        if match:
            assert match.group(1) in known, f"{path.name}: unknown down_revision {match.group(1)!r}"


def test_file_name_starts_with_its_revision_id():
    for name, rev in _revisions().items():
        assert name == f"{rev}.py", f"{name} holds revision {rev!r}"
