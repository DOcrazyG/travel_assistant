"""enable multiple local accounts

Revision ID: 9b2c7914a9d6
Revises: 373c9d3f1e26
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op


revision: str = "9b2c7914a9d6"
down_revision: str | Sequence[str] | None = "373c9d3f1e26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the partial index that enforced the retired single-user scope."""

    op.execute("DROP INDEX IF EXISTS app.uq_users_single_active_account")


def downgrade() -> None:
    """Restore the old constraint only when the data is compatible with it."""

    op.execute(
        "CREATE UNIQUE INDEX uq_users_single_active_account "
        "ON app.users ((true)) WHERE deleted_at IS NULL"
    )
