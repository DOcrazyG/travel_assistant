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
