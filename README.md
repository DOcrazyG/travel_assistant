# Travel Assistant

A production-oriented backend foundation for a travel assistant. The current stage provides a FastAPI baseline, health checks, locked dependencies, tests, and code-quality tooling. The travel Agent, conversations, and database features will be added in later iterations.

## Quick start

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required.

```bash
cp .env.example .env
docker compose up -d mysql
uv sync --all-groups
./start_fastapi.sh
```

The service listens on `http://127.0.0.1:8000` by default. Available endpoints:

- `GET /health/live`: liveness probe
- `GET /health/ready`: readiness probe
- `GET /docs`: OpenAPI documentation

`start_fastapi.sh` starts the application by running `python -m app.main` through `uv`. `make run` remains available for auto-reload development.

Application settings use standard names such as `APP_NAME`, `APP_DEBUG`, `MYSQL_HOST`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD`. `APP_DEBUG` is intentionally more specific than a generic `DEBUG` variable, preventing host-environment conflicts. LLM and LangSmith settings remain in `.env.example` for the future Agent implementation.

MySQL 8.4 is supplied for local development through [docker-compose.yml](docker-compose.yml). Use `make mysql-up` and `make mysql-down` as shortcuts to start and stop the database. FastAPI verifies the MySQL connection during startup and releases its pool during shutdown.

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
