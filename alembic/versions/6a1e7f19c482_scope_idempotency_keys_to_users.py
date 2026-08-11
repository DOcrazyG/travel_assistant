"""scope idempotency keys to authenticated users

Revision ID: 6a1e7f19c482
Revises: 18c1a4ee4f77
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6a1e7f19c482"
down_revision: str | Sequence[str] | None = "18c1a4ee4f77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace retired global idempotency keys with a direct user-owned scope."""

    # No endpoint writes idempotency records before this revision. Expiring any
    # pre-release records preserves the 24-hour retention promise while making
    # the ownership boundary unambiguous for all subsequent writes.
    op.execute("DELETE FROM app.idempotency_keys")
    op.execute(
        "ALTER TABLE app.idempotency_keys ADD COLUMN user_id UUID NOT NULL REFERENCES app.users(id)"
    )
    op.execute("DROP INDEX app.uq_idempotency_keys_request")
    op.execute(
        "CREATE UNIQUE INDEX uq_idempotency_keys_request "
        "ON app.idempotency_keys (user_id, http_method, route, idempotency_key)"
    )
    op.execute(
        "CREATE INDEX ix_idempotency_keys_user_expiry ON app.idempotency_keys (user_id, expires_at)"
    )


def downgrade() -> None:
    """Refuse a lossy downgrade after users may have reused the same key."""

    raise RuntimeError(
        "Cannot safely restore global idempotency-key uniqueness after multi-user writes."
    )
