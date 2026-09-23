"""The hazard taxonomy's event types, and the social and news source types

Revision ID: 0011_hazard_and_source_enums
Revises: 0010_report_submitted_by
Create Date: 2026-09-23

**Phase 1 T1–T2.** `event_type_enum` held four flood types, so a heatwave, a fog
event or a dust storm had no value to be stored as: the PS's categories could
not reach the database at all. This adds the twelve that
`app/services/hazards.py` describes.

It also adds the two source types Phase 2's feeds need: `SOCIAL_MEDIA` for
Mastodon posts and `NEWS_MEDIA` for news items. A post is never stored as
`TWITTER_IMD` — a row naming a platform it did not come from is a fabricated
source, the rule `station_poller` already applies to Open-Meteo versus IMD.

Added the way 0003 added `HUMAN_APPROVED`: plainly, inside the migration's
transaction. Postgres 16 allows `ADD VALUE` there; what it forbids is *using* a
new value before that transaction commits. `alembic/env.py` runs every pending
migration in one transaction, so nothing in this migration or the ones after it
in the same run may write or reference the new values — and nothing does.

Downgrade is a no-op, as in 0003: Postgres has no `ALTER TYPE … DROP VALUE`.
Values nothing writes are harmless, and `IF NOT EXISTS` makes a re-upgrade safe.
"""

from alembic import op

revision = "0011_hazard_and_source_enums"
down_revision = "0010_report_submitted_by"
branch_labels = None
depends_on = None

# Spelled out rather than imported from app.models: a migration is a record of
# what was added at this revision, and must not change when the model does.
NEW_EVENT_TYPES = (
    "RAINFALL",
    "THUNDERSTORM",
    "LIGHTNING",
    "HAILSTORM",
    "DUST_STORM",
    "STRONG_WIND",
    "CYCLONE",
    "HEATWAVE",
    "COLD_WAVE",
    "FOG",
    "LANDSLIDE",
    "UNCLASSIFIED",
)
NEW_SOURCE_TYPES = ("SOCIAL_MEDIA", "NEWS_MEDIA")


def upgrade() -> None:
    for value in NEW_EVENT_TYPES:
        op.execute(f"ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS '{value}'")
    for value in NEW_SOURCE_TYPES:
        op.execute(f"ALTER TYPE source_type_enum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE; the values stay, unused.
    pass
