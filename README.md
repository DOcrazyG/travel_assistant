# Travel Assistant

A production-oriented backend foundation for a travel assistant. The current stage provides a FastAPI baseline, health checks, locked dependencies, tests, and code-quality tooling. The travel Agent, conversations, and database features will be added in later iterations.

## Quick start

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required.

```bash
cp .env.example .env
docker compose up -d postgres valkey
uv sync --all-groups
uv run alembic upgrade head
./start_fastapi.sh
```

The service listens on `http://127.0.0.1:8000` by default. Available endpoints:

- `GET /health/live`: liveness probe
- `GET /health/ready`: readiness probe
- `GET /docs`: OpenAPI documentation

`start_fastapi.sh` starts the application by running `python -m app.main` through `uv`. `make run` remains available for auto-reload development.

## Local-account authentication

The service provides open local-account registration and email/password login. Apply the
latest migration before using these protected endpoints:

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Login and refresh return a 15-minute bearer access token. Login also sets a rotating,
30-day HttpOnly refresh-token cookie. Configure `CORS_ALLOWED_ORIGINS`, replace the two
development-only keys in `.env.example`, and enable secure cookies before deploying.

At startup, the application ensures that one administrator account exists. Before the
first start, set `BOOTSTRAP_ADMIN_EMAIL` and a strong `BOOTSTRAP_ADMIN_PASSWORD` in
`.env`; the values are used only if no non-deleted administrator exists. Later starts
never reset or replace that administrator's password.

Application settings use standard names such as `APP_NAME`, `APP_DEBUG`, `POSTGRES_HOST`, `POSTGRES_DATABASE`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. `APP_DEBUG` is intentionally more specific than a generic `DEBUG` variable, preventing host-environment conflicts. LLM and LangSmith settings remain in `.env.example` for the future Agent implementation.

Application tables are versioned by Alembic. Run `uv run alembic upgrade head` before starting a new environment; `./start_fastapi.sh` and `make run` do this automatically for local development. Create a reviewed migration after model changes with `make revision message="describe change"`. Production deployment runs migrations once as a separate release step, before starting API replicas.

PostgreSQL 16 (Alpine) and Valkey are supplied for local development through [docker-compose.yml](docker-compose.yml). Use `make up` and `make down` as shortcuts to start and stop local infrastructure. FastAPI verifies the PostgreSQL connection during startup and releases its pool during shutdown. Valkey is used for authentication and conversation-management rate limits, with an explicit in-memory fallback available only for local development and tests. Durable idempotency records use PostgreSQL and are scoped to the authenticated user. The project also includes LangGraph's PostgreSQL checkpoint integration for the forthcoming Agent runtime.

Valkey requires `VALKEY_PASSWORD` and is mapped only to `127.0.0.1` in local Compose. Generate the password with `uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`, set it in `.env`, and keep `REDIS_URL=redis://127.0.0.1:6379/0`. Production uses a private network, an ACL-restricted service user, and TLS whenever Valkey traffic crosses hosts or network boundaries.

On startup, the service connects to `POSTGRES_ADMIN_DATABASE` (default: `postgres`) and creates `POSTGRES_DATABASE` when it does not yet exist. The configured PostgreSQL role therefore needs `CREATE DATABASE` permission; the local Compose role has it by default.

## Development commands

```bash
make format              # Format source code
make lint                # Run Ruff checks
make typecheck           # Run Pyright
make test                # Run tests
make check               # Run lint, type checking, and tests
make migrate             # Upgrade application schema to the latest Alembic revision
make revision message=... # Generate a candidate migration from SQLModel metadata
make pre-commit-install  # Install local Git hooks
```

## Current scope

The original command-line Agent and travel-tool implementation have been removed. New functionality will be implemented directly under `app/` according to the architecture design, without migrating the previous prototype.

## Documentation

- [Backend architecture design](docs/architecture-design.md)
- [Conversation API and identity contract](docs/conversation-api-design.md)
- [Database design](docs/database-design.md)
- [Database migration guide](docs/database-migrations.md)
- [Iteration plan](docs/todo-plan.md)
