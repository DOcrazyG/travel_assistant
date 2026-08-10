# Database Migration Guide

**Status:** Implemented

This project uses Alembic to version application-owned PostgreSQL tables. The current baseline revision is `373c9d3f1e26` (`create application schema`). It creates the `app` schema, its current 21 tables, indexes, constraints, JSONB defaults, and UTC `timestamptz` columns.

## Scope and ownership

| Boundary | Versioned by | Notes |
| --- | --- | --- |
| `app` schema | This repository's Alembic revisions | Identity, conversations, messages, attachments, runs, audit, and preferences |
| `public.alembic_version` | Alembic | Stores the applied application revision |
| `langgraph` schema | LangGraph/PostgresSaver setup | Dependency-owned checkpoint state; never added to application metadata or Alembic revisions |
| MinIO buckets and lifecycle policy | Infrastructure provisioning | Object bytes and bucket configuration are not PostgreSQL migrations |

Alembic imports `app.models` before reading `SQLModel.metadata`; therefore every application model must be exported from `app/models/__init__.py`. Migrations use the same typed PostgreSQL settings as the service, so there is no separate database URL to maintain.

## Daily commands

```bash
# Apply all application migrations to the configured database.
make migrate

# Generate a candidate migration after changing SQLModel metadata.
make revision message="add conversation summary"

# Inspect the current revision and compare metadata with the database.
uv run alembic current
uv run alembic check

# Show migration heads and history.
uv run alembic heads
uv run alembic history
```

`make run` and `./start_fastapi.sh` automatically run `alembic upgrade head` for local development. They are convenient for a single local process, not a production deployment mechanism.

## Creating a migration

1. Change the appropriate SQLModel module under `app/models/`, keeping the model import registered by `app.models`.
2. Add or update metadata tests for the table, constraint, index, or type.
3. Run `make revision message="short imperative description"`.
4. Review the generated revision under `alembic/versions/` before committing it.
5. Apply it to an empty database and an upgrade-compatible database copy.
6. Run `uv run alembic check`, `make check`, and the relevant integration tests.

Autogeneration is a draft, not an approval. Manually review every generated foreign key, check constraint, partial index, server default, nullable change, and destructive statement. Schema creation or deletion also requires explicit operations because it is not inferred automatically from SQLModel metadata.

## Review checklist

- Confirm the revision has exactly one parent and the repository has one head.
- Preserve tenant isolation: tenant-scoped foreign keys use `(id, tenant_id)` where the referenced parent is tenant-scoped.
- Use `timestamptz` for persisted time values and UTC application timestamps.
- Express PostgreSQL JSON defaults as SQL expressions, for example `text("'{}'::jsonb")`, rather than a quoted Python string.
- Create indexes for real authorization, history, retention, or worker queries; do not add speculative indexes.
- Make data migrations resumable and bounded. For large production tables, prefer expand/backfill/contract revisions over a long blocking change.
- State rollback behavior in the revision or release notes. A downgrade is not automatically safe once user data has been transformed or deleted.

## Deployment sequence

Run migrations once per release, before starting or replacing API replicas:

```text
backup / verify restore → deploy migration artifact → alembic upgrade head
→ alembic current + health check → start or roll API replicas
```

Only one deployment worker should run Alembic. API replicas must not compete to upgrade the schema at startup. A failed migration stops the release; diagnose the revision and restore or perform a reviewed rollback rather than modifying the `alembic_version` table by hand.

## Local recovery

For an unimportant local development database, recreate the database and run `make migrate`. To inspect a rollback path without changing the migration history, use an isolated database and run `uv run alembic downgrade <revision>` followed by `uv run alembic upgrade head`.

Do not use downgrade as a routine production recovery mechanism. Production data migrations, retention purges, and changes consumed by already-deployed code may be irreversible; restore from a tested backup or ship a forward fix when rollback would lose data.
