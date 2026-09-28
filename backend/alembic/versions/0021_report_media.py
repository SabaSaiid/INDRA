"""Report media: photos and videos, their metadata, hashes and flags

Revision ID: 0021_report_media
Revises: 0020_verification_v2
Create Date: 2026-09-28

**Phase 5 T1, T2, T4.** The plan calls this `0019_report_media`; 0019 and 0020
were taken by the operator passwords (PR #46) and Phase 4, so it is 0021.

`report_media` — one row per photo or video attached to a report, from the
moment its upload starts:

* **The upload session** (webpage.MD §8.3): `status` goes `uploading →
  processing → ready`, or `rejected` with a `reason`. `s3_upload_id` is the
  object store's multipart upload; the parts received are read back from the
  store (ListParts), so there is no second copy here to drift. `declared_mime`
  and `declared_size` are what the phone said before sending anything.
* **Where the bytes are.** `object_key` is the private original
  (`originals/{yyyy}/{mm}/{dd}/{report_id}/{sha256}.{ext}`; for a Mastodon
  attachment, `social/…`). `derivative_key`, `poster_key` and `thumb_key` are
  the copies with every metadata tag removed, which is all that is ever served
  to officials by default (T5). `*_deleted_at` record retention.
* **What was read from it** (T2): `sha256` (exact identity), `phash` (a 64-bit
  perceptual hash that survives resizing and re-compression), `frame_phashes`
  (a video's frames at 1 s, 25%, 50% and 75%), the dimensions, the duration,
  and the EXIF capture time with its offset, GPS, make, model and software.
* **What the rules said** (T3): `flags` and, per flag, why (`flag_basis`).
* `origin` is `citizen` or `social`; a social attachment keeps the author's
  own `source_url`, which is the only link INDRA ever shows for it.

Indexes: `sha256` (the duplicate check), `report_id`, `status`, and a unique
(report_id, source_url) so a backfill can never hash the same attachment twice.

`audit_action_enum` gains `MEDIA_ORIGINAL_ACCESS`: an analyst was given a link
to an original, EXIF and GPS included (T5, webpage.MD §8.5).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0021_report_media"
down_revision = "0020_verification_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_media",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            UUID(as_uuid=True),
            sa.ForeignKey("raw_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(16), nullable=False, server_default="citizen"),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        # The upload session.
        sa.Column("declared_mime", sa.String(100), nullable=True),
        sa.Column("declared_size", sa.BigInteger, nullable=True),
        sa.Column("parts", sa.Integer, nullable=True),
        sa.Column("s3_upload_id", sa.Text, nullable=True),
        sa.Column("incoming_key", sa.Text, nullable=True),
        # Where the bytes are.
        sa.Column("object_key", sa.Text, nullable=True),
        sa.Column("derivative_key", sa.Text, nullable=True),
        sa.Column("poster_key", sa.Text, nullable=True),
        sa.Column("thumb_key", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        # What was read from it.
        sa.Column("mime", sa.String(100), nullable=True),
        sa.Column("bytes", sa.BigInteger, nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("phash", sa.BigInteger, nullable=True),
        sa.Column("frame_phashes", ARRAY(sa.BigInteger), nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("exif_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exif_offset", sa.String(8), nullable=True),
        sa.Column("exif_lat", sa.Float, nullable=True),
        sa.Column("exif_lng", sa.Float, nullable=True),
        sa.Column("exif_make", sa.Text, nullable=True),
        sa.Column("exif_model", sa.Text, nullable=True),
        sa.Column("exif_software", sa.Text, nullable=True),
        # What the rules said.
        sa.Column("flags", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("flag_basis", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("derivatives_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('image', 'video')", name="ck_report_media_kind"),
        sa.CheckConstraint(
            "status IN ('uploading', 'processing', 'ready', 'rejected', 'withdrawn')",
            name="ck_report_media_status",
        ),
        sa.CheckConstraint("origin IN ('citizen', 'social')", name="ck_report_media_origin"),
    )
    op.create_index("ix_report_media_report_id", "report_media", ["report_id"])
    op.create_index("ix_report_media_sha256", "report_media", ["sha256"])
    op.create_index("ix_report_media_status", "report_media", ["status"])
    op.create_index(
        "uq_report_media_source_url",
        "report_media",
        ["report_id", "source_url"],
        unique=True,
        postgresql_where=sa.text("source_url IS NOT NULL"),
    )

    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'MEDIA_ORIGINAL_ACCESS'")


def downgrade() -> None:
    op.drop_index("uq_report_media_source_url", table_name="report_media")
    op.drop_index("ix_report_media_status", table_name="report_media")
    op.drop_index("ix_report_media_sha256", table_name="report_media")
    op.drop_index("ix_report_media_report_id", table_name="report_media")
    op.drop_table("report_media")
    # MEDIA_ORIGINAL_ACCESS stays in audit_action_enum: Postgres has no DROP
    # VALUE, and ledger rows that carry it can never be deleted anyway.
