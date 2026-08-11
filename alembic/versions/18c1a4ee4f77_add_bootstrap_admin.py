"""add bootstrap administrator support

Revision ID: 18c1a4ee4f77
Revises: 9b2c7914a9d6
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op


revision: str = "18c1a4ee4f77"
down_revision: str | Sequence[str] | None = "9b2c7914a9d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add one explicit bootstrap-admin marker without a general roles system."""

    op.execute("ALTER TABLE app.users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_single_admin "
        "ON app.users ((true)) WHERE is_admin IS TRUE AND deleted_at IS NULL"
    )


def downgrade() -> None:
    """Remove the bootstrap-admin marker and its uniqueness guarantee."""

    op.execute("DROP INDEX IF EXISTS app.uq_users_single_admin")
    op.execute("ALTER TABLE app.users DROP COLUMN is_admin")
