"""Clear the placeholder values 0008 seeded into the four operator profiles

Revision ID: 0018_clear_profile_placeholders
Revises: 0017_report_hazard_columns
Create Date: 2026-09-25

0008 seeded one profile per account, which is right: the accounts exist. But it
also gave each of them values nobody issued:

* badge numbers `NDMA-ADM-001`, `SDMA-CMD-001`, `IMD-ANL-001`, `CIT-REP-001`;
* callsigns `CONTROL`, `PATNA-ACTUAL`, `SIGNAL`, `GROUND` (`PATNA-ACTUAL` named
  after a scenario that was itself invented);
* team role `Operational Specialist`, from 0002's server default, because the
  seed never set one;
* the citizen's agency `Community Weather Watch`, an organisation that does not
  exist, where the account itself has always said `PUBLIC`.

The dashboard showed all of them as though someone had assigned them. They are
set to NULL here (the agency to `PUBLIC`, since the column is NOT NULL), and
the two server defaults that invented values for every new row are dropped:
`user_profiles.team_role` ('Operational Specialist') and
`teams.members_count` (12, a head-count nobody reported; the column stays NOT
NULL, so a team must now say how many it has).

Each UPDATE matches the exact seeded value, so a value an operator has since
set through PATCH /api/profile/me is left alone. `full_name` keeps the generic
role titles ('Incident Commander' and so on), which describe the account
rather than a person.

Downgrade restores both defaults, and puts the seeded values back only where
the column is still NULL (or, for the agency, still `PUBLIC`).
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_clear_profile_placeholders"
down_revision = "0017_report_hazard_columns"
branch_labels = None
depends_on = None

# username → (badge_number, callsign), exactly as 0008 seeded them.
SEEDED = {
    "admin": ("NDMA-ADM-001", "CONTROL"),
    "commander": ("SDMA-CMD-001", "PATNA-ACTUAL"),
    "analyst": ("IMD-ANL-001", "SIGNAL"),
    "citizen": ("CIT-REP-001", "GROUND"),
}
SEEDED_TEAM_ROLE = "Operational Specialist"
SEEDED_CITIZEN_AGENCY = "Community Weather Watch"
TEAM_SIZE_DEFAULT = "12"


def upgrade() -> None:
    conn = op.get_bind()

    op.alter_column("user_profiles", "team_role", server_default=None)
    op.alter_column("teams", "members_count", server_default=None)

    for username, (badge, callsign) in SEEDED.items():
        conn.execute(
            sa.text(
                "UPDATE user_profiles SET badge_number = NULL "
                "WHERE username = :username AND badge_number = :badge"
            ),
            {"username": username, "badge": badge},
        )
        conn.execute(
            sa.text(
                "UPDATE user_profiles SET callsign = NULL "
                "WHERE username = :username AND callsign = :callsign"
            ),
            {"username": username, "callsign": callsign},
        )

    conn.execute(
        sa.text(
            "UPDATE user_profiles SET team_role = NULL "
            "WHERE username = ANY(:names) AND team_role = :team_role"
        ),
        {"names": list(SEEDED), "team_role": SEEDED_TEAM_ROLE},
    )
    conn.execute(
        sa.text(
            "UPDATE user_profiles SET agency = 'PUBLIC' "
            "WHERE username = 'citizen' AND agency = :agency"
        ),
        {"agency": SEEDED_CITIZEN_AGENCY},
    )


def downgrade() -> None:
    conn = op.get_bind()

    op.alter_column("teams", "members_count", server_default=TEAM_SIZE_DEFAULT)
    op.alter_column("user_profiles", "team_role", server_default=SEEDED_TEAM_ROLE)

    for username, (badge, callsign) in SEEDED.items():
        conn.execute(
            sa.text(
                "UPDATE user_profiles SET badge_number = :badge "
                "WHERE username = :username AND badge_number IS NULL"
            ),
            {"username": username, "badge": badge},
        )
        conn.execute(
            sa.text(
                "UPDATE user_profiles SET callsign = :callsign "
                "WHERE username = :username AND callsign IS NULL"
            ),
            {"username": username, "callsign": callsign},
        )

    conn.execute(
        sa.text(
            "UPDATE user_profiles SET team_role = :team_role "
            "WHERE username = ANY(:names) AND team_role IS NULL"
        ),
        {"names": list(SEEDED), "team_role": SEEDED_TEAM_ROLE},
    )
    conn.execute(
        sa.text(
            "UPDATE user_profiles SET agency = :agency "
            "WHERE username = 'citizen' AND agency = 'PUBLIC'"
        ),
        {"agency": SEEDED_CITIZEN_AGENCY},
    )
