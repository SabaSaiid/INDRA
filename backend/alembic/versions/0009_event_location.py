"""Where an event is, and when it last changed

Revision ID: 0009_event_location
Revises: 0008_seed_operator_profiles
Create Date: 2026-09-22

Two columns' worth of missing schema, behind two separate defects.

**Location (BUG-033).** Neither `raw_reports` nor `verified_events` has ever
had a place-name column. `GET /api/events` read the name out of
`verification_receipt->>'city'`, a key the live pipeline never writes — the
only writer in the repo is the synthetic seeder — so every real event reached
the console as `"city": "Unknown"` while demo data looked fine. The receipt is
a scoring artefact and a poor place to keep a location, so this adds real
columns: queryable, indexable, and answerable by the database rather than by a
fallback string.

`place_precision` travels with the name for the same reason `factor_coverage`
travels with the confidence score. It records whether the point was inside the
district (`district`) or merely near it (`near`), so a label can hedge when the
resolver hedged. All three columns are nullable and are genuinely left NULL
when the resolver declines — a point in the Bay of Bengal gets no name, and
"we do not know" stays distinguishable from "somewhere in India".

**`updated_at` (BUG-035).** `_find_mergeable_event` gates on
`verified_at > NOW() - MERGE_WINDOW_MINUTES`, but the merge branch updates an
event's score, severity and receipt without ever touching `verified_at`, which
is an insert-time default. The window was therefore keyed on *creation* time:
an event closed to new reports two hours after it was born no matter how
recently it had absorbed one. A report 50 m from a live event's centroid was
dropped on exactly this path. `verified_at` keeps meaning "created" — other
code and the API's time filters depend on that — and the merge window moves to
a column that means what the window needs.

Existing rows are backfilled: `updated_at` from `verified_at`, and the one
event in the demo database gets its district from the same resolver the
pipeline now uses, so no rebuild is needed to see the fix.

Downgrade drops all four columns. It does not try to fold the names back into
the receipt: they were never there.
"""

import logging

from alembic import op
import sqlalchemy as sa

revision = "0009_event_location"
down_revision = "0008_seed_operator_profiles"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.0009")


def upgrade() -> None:
    op.add_column("verified_events", sa.Column("district", sa.String(120), nullable=True))
    op.add_column("verified_events", sa.Column("state", sa.String(120), nullable=True))
    op.add_column("verified_events", sa.Column("place_precision", sa.String(16), nullable=True))
    op.add_column(
        "verified_events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )

    op.add_column("raw_reports", sa.Column("district", sa.String(120), nullable=True))
    op.add_column("raw_reports", sa.Column("state", sa.String(120), nullable=True))

    # An event that has never been merged into has not changed since it was
    # created, so its creation time is the honest starting value.
    op.execute("UPDATE verified_events SET updated_at = verified_at WHERE updated_at IS NULL")

    _backfill_places()


def _backfill_places() -> None:
    """
    Name the rows that already exist, using the same resolver the pipeline
    now uses, so the two can never disagree about a point.

    Best-effort by design. A backfill that cannot resolve a row leaves it NULL,
    which is the same thing the live path does, and an import failure here must
    not block the schema change — the columns are the migration, the names are
    a convenience.
    """
    try:
        from app.services.geocoding import reverse_geocode
    except Exception as exc:  # pragma: no cover - environment, not logic
        logger.warning(f"Skipping location backfill, resolver unavailable: {exc}")
        return

    connection = op.get_bind()

    events = connection.execute(sa.text(
        "SELECT id, ST_Y(center_point) AS lat, ST_X(center_point) AS lng "
        "FROM verified_events WHERE center_point IS NOT NULL"
    )).fetchall()

    named = 0
    for row in events:
        place = reverse_geocode(row.lat, row.lng)
        if place is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE verified_events SET district = :d, state = :s, place_precision = :p "
                "WHERE id = :id"
            ),
            {"d": place.district, "s": place.state, "p": place.precision, "id": row.id},
        )
        named += 1

    reports = connection.execute(sa.text(
        "SELECT id, latitude, longitude FROM raw_reports"
    )).fetchall()

    named_reports = 0
    for row in reports:
        place = reverse_geocode(row.latitude, row.longitude)
        if place is None:
            continue
        connection.execute(
            sa.text("UPDATE raw_reports SET district = :d, state = :s WHERE id = :id"),
            {"d": place.district, "s": place.state, "id": row.id},
        )
        named_reports += 1

    logger.info(
        f"Location backfill: named {named}/{len(events)} events "
        f"and {named_reports}/{len(reports)} reports"
    )


def downgrade() -> None:
    op.drop_column("raw_reports", "state")
    op.drop_column("raw_reports", "district")
    op.drop_column("verified_events", "updated_at")
    op.drop_column("verified_events", "place_precision")
    op.drop_column("verified_events", "state")
    op.drop_column("verified_events", "district")
