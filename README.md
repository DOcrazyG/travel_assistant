# Travel Assistant

A production-oriented backend foundation for a travel assistant. The current stage provides a FastAPI baseline, health checks, locked dependencies, tests, and code-quality tooling. The travel Agent, conversations, and database features will be added in later iterations.

## Quick start

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required.

```bash
cp .env.example .env
uv sync --all-groups
./start_fastapi.sh
```

The service listens on `http://127.0.0.1:8000` by default. Available endpoints:

- `GET /health/live`: liveness probe
- `GET /health/ready`: readiness probe
- `GET /docs`: OpenAPI documentation

`start_fastapi.sh` starts the application by running `python -m app.main` through `uv`. `make run` remains available for auto-reload development.

Application settings use the `TRAVEL_ASSISTANT_` prefix, for example `TRAVEL_ASSISTANT_DEBUG=true`, so generic host-environment variables cannot conflict with the application. LLM and LangSmith settings remain in `.env.example` for the future Agent implementation.

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
