# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""participants.invited_at

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLE = "participants"
COLUMN = "invited_at"


def _has_column(bind) -> bool:
    return COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    # As in 0002: revision 0001 is `create_all()`, so a fresh database is built
    # from the current models and already has this column. Without the check,
    # every new install fails at startup on a duplicate column.
    bind = op.get_bind()
    if not _has_column(bind):
        op.add_column(TABLE, sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        with op.batch_alter_table(TABLE) as batch:  # SQLite cannot drop in place
            batch.drop_column(COLUMN)
