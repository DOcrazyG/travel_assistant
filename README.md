# Travel Assistant

[中文文档](docs/README.zh-CN.md)

Travel Assistant is a FastAPI backend for an authenticated, persistent travel-assistant
conversation experience. It provides local-account authentication, PostgreSQL-backed
conversations and idempotency, a LangGraph checkpointed single-agent runtime, and both
JSON and Server-Sent Events (SSE) responses.

## What is implemented

- Email/password registration, short-lived JWT access tokens, and rotating HttpOnly
  refresh-token cookies.
- Per-user conversation creation, listing, history retrieval, and soft deletion.
- A text-only, OpenAI-compatible LLM conversation endpoint with durable history.
- JSON responses and ordered SSE streaming responses for each agent turn.
- PostgreSQL schema migrations managed by Alembic and LangGraph checkpoint tables.
- PostgreSQL readiness checks plus Valkey-backed rate limiting, with a development-only
  in-memory fallback.
- Structured logs, request IDs, a consistent error envelope, and automated checks.

The current agent accepts text input only. The request protocol includes image, file,
and function-tool shapes for future expansion, but those inputs are intentionally
rejected by the live conversation endpoint.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose (for the supplied local PostgreSQL and Valkey services)
- An OpenAI-compatible API key, base URL, and model name to send agent messages

## Quick start

1. Create local configuration and set the required development values. In particular,
   replace `VALKEY_PASSWORD`; configure `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and
   `DEFAULT_LLM_MODEL` before using the conversation endpoint.

   ```bash
   cp .env.example .env
   ```

2. Install Python dependencies and start local infrastructure.

   ```bash
   uv sync --all-groups
   docker compose up -d postgres valkey
   ```

3. Start the API.

   ```bash
   sh start_fastapi.sh
   ```

   The script applies Alembic migrations, creates LangGraph checkpoint tables, then
   launches `python -m app.main`. By default, `APP_DEBUG=true` enables Uvicorn reload
   mode and the API listens at `http://127.0.0.1:8000`.

4. Confirm the process is running.

   ```bash
   curl http://127.0.0.1:8000/health/live
   curl http://127.0.0.1:8000/health/ready
   ```

   Interactive OpenAPI documentation is available at
   [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### Port already in use

The server uses `HOST` and `PORT` from `.env` (`127.0.0.1:8000` by default). If startup
ends with `ERROR: [Errno 98] Address already in use`, a service is already listening on
that address. Stop the previous instance or set an unused `PORT` in `.env`, for example
`PORT=8001`, and start again. On Linux, inspect the listener with:

```bash
ss -ltnp '( sport = :8000 )'
```

## Configuration

`.env.example` documents every setting. Do not commit the copied `.env` file or any
secrets. The most important groups are:

| Purpose | Settings |
| --- | --- |
| HTTP server | `HOST`, `PORT`, `APP_DEBUG`, `LOG_LEVEL`, `LOG_FORMAT` |
| PostgreSQL | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DATABASE`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| Valkey / rate limits | `REDIS_URL`, `VALKEY_USERNAME`, `VALKEY_PASSWORD`, `ALLOW_IN_MEMORY_RATE_LIMIT` |
| Authentication | `JWT_SECRET_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_MINUTES`, `REFRESH_SESSION_DAYS`, `CORS_ALLOWED_ORIGINS` |
| Initial administrator | `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` |
| Model provider | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `DEFAULT_LLM_MODEL`, `FALLBACK_LLM_MODEL` |

At startup, the application creates `POSTGRES_DATABASE` if necessary, so the configured
PostgreSQL role must have permission to create that database. It also creates the
bootstrap administrator only when no non-deleted administrator exists; subsequent starts
never reset that account's password.

For staging and production, use strong unique values for `JWT_SECRET_KEY` and
`PII_HASH_KEY`, configure `CORS_ALLOWED_ORIGINS`, enable secure refresh cookies, and use
a reachable Valkey service with credentials. The application refuses unsafe production
configuration. The included Compose file publishes database ports; restrict access with
host firewall rules or change the port bindings when that is not appropriate.

## API overview

All protected endpoints require `Authorization: Bearer <access_token>`. The API returns
errors in a consistent shape containing `code`, `message`, and `request_id`; validation
errors also contain safe field details.

| Endpoint | Description |
| --- | --- |
| `GET /health/live` | Liveness probe |
| `GET /health/ready` | Readiness probe after database initialization |
| `POST /api/v1/auth/register` | Create a local account |
| `POST /api/v1/auth/login` | Return an access token and set a refresh-token cookie |
| `POST /api/v1/auth/refresh` | Rotate the refresh cookie and issue a new access token |
| `POST /api/v1/auth/logout` | Revoke the current session/token and clear the cookie |
| `GET /api/v1/auth/me` | Return the current account |
| `POST /api/v1/conversations` | Create an empty conversation |
| `GET /api/v1/conversations` | List the caller's conversations |
| `GET /api/v1/conversations/{id}` | Fetch a conversation and the first page of messages |
| `GET /api/v1/conversations/{id}/messages` | Fetch paginated message history |
| `POST /api/v1/conversations/{id}/messages` | Submit one agent turn as JSON or SSE |
| `DELETE /api/v1/conversations/{id}` | Soft-delete a conversation |

`offset` and `limit` pagination parameters are supported by conversation and message
listing endpoints. Limits are 1–100; the default is 20 for conversation lists and 50
for message history.

### Basic API flow

Register, log in, then create a conversation. `jq` is used below only to extract values;
you may substitute another JSON tool.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"traveler@example.com","password":"a-long-local-password"}'

TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"traveler@example.com","password":"a-long-local-password"}' \
  | jq -r '.access_token')

CONVERSATION_ID=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/conversations \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Japan itinerary"}' \
  | jq -r '.id')
```

Submit a non-streaming text message. `Idempotency-Key` is required: reuse the same key
only to safely retry the exact same request.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: 8e8b8b6f-1a79-4d59-88b8-unique-request-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "input": {
      "role": "user",
      "content": [{"type": "input_text", "text": "Plan a five-day Tokyo trip."}]
    }
  }'
```

To stream, add `"stream": true` to the request body and request an event stream. Events
are sent in order, including `response.created`, `response.output_text.delta`,
`response.completed`; failed runs emit `response.failed` and `error`.

```bash
curl -N -X POST "http://127.0.0.1:8000/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: a-different-unique-request-key' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{
    "stream": true,
    "input": {
      "role": "user",
      "content": [{"type": "input_text", "text": "What should I reserve first?"}]
    }
  }'
```

The full request and response contract is described in
[Conversation API and identity contract](docs/conversation-api-design.md), and `/docs`
is the source of truth for the running API schema.

## Data and runtime behavior

Application tables are managed by Alembic. LangGraph PostgreSQL checkpoint tables are
owned by the LangGraph dependency and are initialized separately; `start_fastapi.sh`,
`make migrate`, and `make run` perform both setup operations locally.

Conversation turns are scoped to the authenticated user. The service persists messages,
agent-run state, idempotency records, and checkpointed graph history in PostgreSQL. The
single-agent runtime calls the configured primary model through an OpenAI-compatible
endpoint; if that call fails and `FALLBACK_LLM_MODEL` is configured, it retries with the
fallback model on the same endpoint.

## Development commands

```bash
make install              # Install all dependency groups with uv
make up                   # Start local PostgreSQL and Valkey
make down                 # Stop local infrastructure
make run                  # Migrate, initialize checkpoints, and run with reload
make migrate              # Apply Alembic migrations and initialize checkpoints
make setup-checkpoints    # Initialize LangGraph checkpoint tables
make revision message='describe change'  # Generate a candidate Alembic migration
make format               # Format source code with Ruff
make lint                 # Run Ruff checks
make typecheck            # Run Pyright
make test                 # Run tests
make check                # Run lint, type checking, and tests
make pre-commit-install   # Install local Git hooks
make smoke-admin          # Log in as bootstrap admin and chat interactively
```

Before `make smoke-admin`, start the API and set `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD` in `.env`. The tool creates a conversation and renders
streaming tokens until `/exit` or Ctrl-D. For a non-default address, run:

```bash
uv run python scripts/admin_conversation_smoke.py --base-url http://host:port
```

Integration tests require a PostgreSQL database and are opt-in:

```bash
RUN_POSTGRES_INTEGRATION=1 uv run pytest tests/integration
```

## Further documentation

- [Backend architecture design](docs/architecture-design.md)
- [Conversation API and identity contract](docs/conversation-api-design.md)
- [Database design](docs/database-design.md)
- [Database migration guide](docs/database-migrations.md)
- [Iteration plan](docs/todo-plan.md)
