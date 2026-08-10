# Travel Assistant

A production-oriented backend foundation for a travel assistant. The current stage provides a FastAPI baseline, health checks, locked dependencies, tests, and code-quality tooling. The travel Agent, conversations, and database features will be added in later iterations.

## Quick start

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required.

```bash
cp .env.example .env
docker compose up -d postgres
uv sync --all-groups
./start_fastapi.sh
```

The service listens on `http://127.0.0.1:8000` by default. Available endpoints:

- `GET /health/live`: liveness probe
- `GET /health/ready`: readiness probe
- `GET /docs`: OpenAPI documentation

`start_fastapi.sh` starts the application by running `python -m app.main` through `uv`. `make run` remains available for auto-reload development.

Application settings use standard names such as `APP_NAME`, `APP_DEBUG`, `POSTGRES_HOST`, `POSTGRES_DATABASE`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. `APP_DEBUG` is intentionally more specific than a generic `DEBUG` variable, preventing host-environment conflicts. LLM and LangSmith settings remain in `.env.example` for the future Agent implementation.

PostgreSQL 16 (Alpine) is supplied for local development through [docker-compose.yml](docker-compose.yml). Use `make up` and `make down` as shortcuts to start and stop the database. FastAPI verifies the PostgreSQL connection during startup and releases its pool during shutdown. The project also includes LangGraph's PostgreSQL checkpoint integration for the forthcoming Agent runtime.

On startup, the service connects to `POSTGRES_ADMIN_DATABASE` (default: `postgres`) and creates `POSTGRES_DATABASE` when it does not yet exist. The configured PostgreSQL role therefore needs `CREATE DATABASE` permission; the local Compose role has it by default.

## Development commands

```bash
make format              # Format source code
make lint                # Run Ruff checks
make typecheck           # Run Pyright
make test                # Run tests
make check               # Run lint, type checking, and tests
make pre-commit-install  # Install local Git hooks
```

## Current scope

The original command-line Agent and travel-tool implementation have been removed. New functionality will be implemented directly under `app/` according to the architecture design, without migrating the previous prototype.

## Documentation

- [Backend architecture design](docs/architecture-design.md)
- [Iteration plan](docs/todo-plan.md)
