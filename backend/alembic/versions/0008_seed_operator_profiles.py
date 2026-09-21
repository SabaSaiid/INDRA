"""Seed user_profiles from the four accounts auth actually authenticates

Revision ID: 0008_seed_operator_profiles
Revises: 0007_agency_alerts
Create Date: 2026-09-21

`user_profiles` has never held a row. `/api/profile/me` therefore always fell
through to `DEMO_PROFILES` in the router — and worse, when a row *did* exist it
still overwrote the statistics with invented ones:

    data["verified_events_triaged"] = role_defaults.get(..., 24)
    data["accuracy_rate"] = role_defaults.get(..., 96.8)

So the operator card claimed a 96.8 % accuracy rate for a figure no code
computes, on a profile that did not exist, next to live event data. That is the
same defect class as the demo events removed on Day 5.

The distinction that matters: **an account is not fabricated telemetry.**
`core/security.py::DEMO_USERS` holds four accounts you can genuinely log in as,
with real bcrypt hashes, real roles and real agencies — they are the demo
deployment's actual identities. Seeding `user_profiles` from exactly those four
makes the profile endpoint truthful: it describes accounts that exist.

Their *statistics* are a different matter and are not seeded here. Counts are
computed from `audit_logs` at read time, so they start at zero and rise as the
operator actually reviews events. `accuracy_rate` stays NULL — nothing in the
platform computes accuracy, and 96.8 would be an invention.

Downgrade deletes exactly these four usernames and nothing else, so a profile
created later by other means survives.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_seed_operator_profiles"
down_revision = "0007_agency_alerts"
branch_labels = None
depends_on = None

# username, full_name, role, agency, operator_id, badge_number, callsign
OPERATORS = [
    ("admin", "System Administrator", "ADMIN", "NDMA", "OP-ADMIN-001", "NDMA-ADM-001", "CONTROL"),
    ("commander", "Incident Commander", "COMMANDER", "SDMA_BIHAR", "OP-CMD-001", "SDMA-CMD-001", "PATNA-ACTUAL"),
    ("analyst", "Verification Analyst", "ANALYST", "IMD", "OP-ANL-001", "IMD-ANL-001", "SIGNAL"),
    ("citizen", "Community Reporter", "CITIZEN", "Community Weather Watch", "OP-CIT-001", "CIT-REP-001", "GROUND"),
]


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("user_profiles")}

    for username, full_name, role, agency, operator_id, badge, callsign in OPERATORS:
        values = {
            "username": username,
            "full_name": full_name,
            "role": role,
            "agency": agency,
            "operator_id": operator_id,
            "duty_status": "ON_DUTY" if role != "CITIZEN" else "OFF_DUTY",
        }
        if "badge_number" in cols:
            values["badge_number"] = badge
        if "callsign" in cols:
            values["callsign"] = callsign

        names = ", ".join(values)
        binds = ", ".join(f":{k}" for k in values)
        conn.execute(
            sa.text(
                f"INSERT INTO user_profiles ({names}) VALUES ({binds}) "
                "ON CONFLICT (username) DO NOTHING"
            ),
            values,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM user_profiles WHERE username = ANY(:names)"),
        {"names": [o[0] for o in OPERATORS]},
    )
