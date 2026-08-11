"""Structural checks for the Alembic migration history."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_history_has_one_head_and_an_initial_schema_revision() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revisions = list(script.walk_revisions())

    assert len(script.get_heads()) == 1

    initial_revision = next(revision for revision in revisions if revision.down_revision is None)

    migration_source = Path(initial_revision.path).read_text(encoding="utf-8")
    assert 'op.execute("CREATE SCHEMA IF NOT EXISTS app")' in migration_source
    assert 'op.execute("DROP SCHEMA IF EXISTS app CASCADE")' in migration_source


def test_multi_account_migration_removes_the_retired_single_user_index() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    migration_source = Path(script.get_revision("9b2c7914a9d6").path).read_text(encoding="utf-8")

    assert "DROP INDEX IF EXISTS app.uq_users_single_active_account" in migration_source


def test_bootstrap_admin_migration_adds_an_explicit_unique_admin_marker() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    migration_source = Path(script.get_revision("18c1a4ee4f77").path).read_text(encoding="utf-8")

    assert "ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false" in migration_source
    assert "CREATE UNIQUE INDEX uq_users_single_admin" in migration_source


def test_idempotency_migration_adds_a_direct_user_scope() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    migration_source = Path(script.get_revision("6a1e7f19c482").path).read_text(encoding="utf-8")

    assert "ADD COLUMN user_id UUID NOT NULL REFERENCES app.users(id)" in migration_source
    assert "(user_id, http_method, route, idempotency_key)" in migration_source
