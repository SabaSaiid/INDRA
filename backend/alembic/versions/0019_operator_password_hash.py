"""Operator password hashes in user_profiles

Revision ID: 0019_operator_password_hash
Revises: 0018_clear_profile_placeholders
Create Date: 2026-09-25

The four accounts in `user_profiles` (0008) were authenticated against a dict
in `core/security.py` that held their passwords in plain text, so anyone who
could read the repository could sign in as any of them. Accounts now
authenticate against this table instead: `password_hash` is a bcrypt hash, and
NULL means the account cannot sign in at all.

No hash is seeded. A bcrypt hash of a known password committed to git gives the
password away as surely as the plain text did, so every deployment sets its own
with `scripts/set_operator_password.py`. Until it does, every login is a 401.

Downgrade drops the column, and every password set since with it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_operator_password_hash"
down_revision = "0018_clear_profile_placeholders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("password_hash", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "password_hash")
