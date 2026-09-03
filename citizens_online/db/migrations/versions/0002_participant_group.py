# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""participants.added_via_group

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLE = "participants"
COLUMN = "added_via_group"


def _has_column(bind) -> bool:
    return COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    # Revision 0001 is `Base.metadata.create_all()`, so a fresh database is built
    # from the current models and already has this column; only an existing one
    # needs the ALTER. Without this check every new install fails at startup.
    bind = op.get_bind()
    if not _has_column(bind):
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        with op.batch_alter_table(TABLE) as batch:  # SQLite cannot drop in place
            batch.drop_column(COLUMN)
