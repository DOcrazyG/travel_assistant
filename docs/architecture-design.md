# Travel Assistant Backend Architecture Design

[中文版本](architecture-design.zh-CN.md)

**Status:** Approved target architecture; P2.0 single-Agent conversation loop implemented
**Last updated:** 2026-08-14
**Applies to:** Building a deployable, maintainable FastAPI and LangGraph service from the engineering baseline

## 1. Context and goals

The repository now contains an engineering and authentication baseline plus a durable, single-Agent conversation loop. The target system is a locally authenticated multi-account travel-assistant backend with HTTP APIs, conversation state, controlled external tools, operational safeguards, and observability.

This design takes inspiration from [fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template): an API layer, LangGraph orchestration, independent services, database migrations, caching, authentication, rate limiting, observability, and evaluation. The first product scope is travel advice and itinerary drafts. Booking, payments, and other irreversible travel decisions are explicitly excluded.

### Goals

- Provide versioned, stream-capable HTTP APIs for travel conversations.
- Use LangGraph for multi-turn state, tool calls, recovery, and human approval.
- Persist conversations, messages, tool calls, and confirmed travel preferences.
- Isolate weather, attractions, routes, and map providers behind replaceable tools.
- Establish authentication, rate limiting, logs, metrics, traces, evaluations, and deployment foundations.

### Non-goals for the first release

- Hotel, flight, ticket, or attraction booking; payment; or ordering on a user's behalf.
- Unrestricted web scraping or arbitrary tool execution.
- Dynamic-pricing commitments, live inventory guarantees, or travel-insurance advice.
- Writing preferences to long-term memory without the user's explicit confirmation.

## 2. Architectural principles

- **Domain first:** Route handlers translate protocols only. Travel rules, tools, and Agent orchestration do not live in route handlers.
- **Explicit state:** Use a typed LangGraph `StateGraph` for execution paths. Nodes return partial state updates only.
- **Recoverable execution:** Every conversation has a public `conversation_id` and an internal stable `thread_id`; production uses a durable checkpoint backend selected for the Agent in P2, never in-memory state.
- **Controlled tools:** Tools use allowlists, parameter validation, timeouts, retries, and audit records. Results retain source and retrieval time.
- **Progressive delivery:** Build an observable travel-advice loop first, then add long-term memory, parallel retrieval, evaluation, and human collaboration.
- **Secure defaults:** Minimize personal-data retention. Load secrets only from the runtime environment. Require explicit confirmation for writes and future high-risk actions.

## 3. System overview

```mermaid
flowchart TB
    Client[Web / Mobile / Internal Client] --> API[FastAPI API v1]
    API --> MW[Middleware\nAuth · Rate limiting · Request context · Audit]
    MW --> Chat[Conversation Service]
    Chat --> Graph[Travel LangGraph]
    Graph --> LLM[LLM Service\nRegistry · Timeout · Retry · Fallback]
    Chat --> Domain[Preference and Itinerary Services - P4]
    Chat --> DB[(PostgreSQL)]
    Domain --> DB
    Graph --> DB
    MW --> Cache[(Redis / Valkey)]
    API --> Obs[Structured logs · Metrics · LLM tracing]
    Obs --> Monitor[Prometheus / Grafana / LangSmith]
```

The diagram above is the broad platform boundary. P2–P5 use one Travel Agent node as the only graph orchestration unit. Capabilities such as preferences, itineraries, observability, and release operations are added around that node through APIs and application services; they do not introduce graph routing, `ToolNode` loops, or multi-Agent delegation.

### Current P2.0 request flow

```mermaid
sequenceDiagram
    participant C as Client
    participant A as FastAPI
    participant G as Travel Graph
    participant D as PostgreSQL

    C->>A: POST /api/v1/conversations/{id}/messages
    A->>A: Authenticate, rate-limit, validate request
    A->>D: Store user message / retrieve thread_id
    A->>G: ainvoke or astream(new message, thread_id, user context)
    G->>D: Restore checkpointed message history
    G->>G: Apply system prompt and call one LLM
    G->>D: Persist updated checkpoint
    G-->>A: Assistant reply or text deltas
    A->>D: Store assistant message and completed run
    A-->>C: JSON response or Responses-style SSE events
```

## 4. Technology choices

| Area | Preferred choice | Responsibility |
| --- | --- | --- |
| API | FastAPI + Pydantic v2 | REST, SSE, OpenAPI, request and response validation |
| Agent orchestration | LangGraph | One checkpointed `START → agent → END` topology for P2–P5; no routing or tool loop. |
| LLM integration | `langchain-openai` in OpenAI-compatible mode | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `DEFAULT_LLM_MODEL`, and optional `FALLBACK_LLM_MODEL` configuration |
| System-management data | PostgreSQL 16 + SQLModel/SQLAlchemy + Alembic | Users, conversations, messages, runs, and migrations |
| LangGraph persistence | `PostgresSaver` on PostgreSQL | Checkpoints by `thread_id`, recovery, and replay |
| Cache and rate limiting | Redis or Valkey, with explicit in-memory development fallback | Hot-query cache, idempotency keys, and rate limits |
| Vector retrieval (phase two) | Dedicated vector store, selected in P4 | Semantic retrieval of confirmed preferences and facts |
| Observability | Structured logging + Prometheus + LangSmith | Diagnostics, metrics, Agent tracing, and evaluation |
| Delivery | Docker, Docker Compose, CI | Consistent local environments, deployment, and automated checks |

Exact versions are locked in `pyproject.toml` and `uv.lock`. New Agent code uses LangChain and LangGraph 1.x rather than legacy 0.x packages.

## 5. Recommended project structure

```text
.
├── app/
│   ├── main.py                     # FastAPI application factory, lifespan, routing
│   ├── api/v1/
│   │   ├── router.py
│   │   ├── conversations.py         # Conversations, SSE, execution resume
│   │   ├── sessions.py               # Session management
│   │   ├── preferences.py            # Confirmed travel preferences
│   │   └── health.py
│   ├── core/
│   │   ├── config.py                 # Settings and environment configuration
│   │   ├── security.py               # JWT and local-account authorization
│   │   ├── middleware.py             # Request IDs, logging context, timings
│   │   ├── limiter.py
│   │   ├── cache.py
│   │   ├── prompts/                  # Versioned system prompts
│   │   └── langgraph/
│   │       ├── graph.py              # Graph assembly and compilation
│   │       ├── state.py              # TravelAgentState
│   │       ├── nodes/                # Routing, planning, answer, memory nodes
│   │       └── tools/                # Weather, attraction, route tools
│   ├── models/                       # ORM models
│   ├── schemas/                      # Pydantic API DTOs
│   ├── services/
│   │   ├── crud/                     # Table-scoped persistence operations
│   │   ├── llm/                      # Model registry, retry, circuit breaker/fallback
│   │   ├── conversation.py
│   │   ├── memory.py
│   │   └── travel/                   # Domain services and provider adapters
│   └── observability/                # Metrics, tracing, audit
├── alembic/                          # Database migrations
├── tests/                            # Unit, integration, API, and regression tests
├── evals/                            # Travel evaluation datasets and reports
├── docs/
├── scripts/
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

The repository currently includes the engineering baseline, SQLModel table metadata,
Alembic migration foundation, a single-node graph in `app/agent/travel.py`, and an
OpenAI-compatible LLM service in `app/services/llm.py`. Prompts and future tools are
implemented directly under `app/`; no previous prototype is migrated.

## 6. Core domain and data model

### Conversation and short-term state

The complete business schema, index strategy, retention, MinIO attachment boundary, and LangGraph schema boundary are defined in [Database design](database-design.md).

- `users`: identity and status. The first release supports authenticated users only; anonymous conversations are out of scope.
- `auth_sessions`, `refresh_tokens`, and `revoked_access_tokens`: self-managed password-login sessions, rotating refresh tokens, and JWT revocation state (`jti`, expiry, revoked timestamp, and minimal device metadata).
- `conversations`: a continuous conversation linked directly to `user_id`, `thread_id`, title, and archive state.
- `messages`: user, assistant, tool, and system messages with ordering, content, citations, and token usage.
- `agent_runs`: graph-execution status, model, duration, errors, and trace ID.
- `tool_calls`: tool name, redacted input, result summary, source, duration, and errors.

`conversations.conversation_id` is the public, unguessable API identifier. It maps one-to-one to the internal `thread_id`, which is the unique join key for LangGraph checkpoints. API calls must provide or receive a server-created conversation; process memory must not represent production session state. The authenticated user is checked against the conversation on every read, write, stream, and resume operation.

### Long-term preferences and memory

- `travel_preferences`: budget range, party size, interests, dietary or accessibility needs, language, visited places, source, confirmation state, and expiration.
- Read only `confirmed` preferences by default. Model-extracted preferences are stored as candidates and become long-term memory only after confirmation.
- In phase two, create embeddings only for confirmed high-value data and retrieve them through user-scoped vector search. Do not indiscriminately store entire chat histories in a vector database.

## 7. LangGraph design

### Current single-Agent state model

`TravelAgentState` currently contains only:

- `messages`: a reducer-backed sequence of serializable `user` and `assistant` messages;
- `final_answer`: the newest assistant text returned to the API layer.

`user_id`, `conversation_id`, and the LLM client are request-scoped `TravelAgentContext`, not checkpoint state. `thread_id` is supplied in the LangGraph invocation configuration and scopes the PostgreSQL checkpoint sequence.

### Current graph

```mermaid
flowchart LR
    Start([START]) --> Agent[Travel Agent]
    Agent --> End([END])
```

For every submitted user message, the Agent restores its `thread_id` history, prepends `TRAVEL_ASSISTANT_SYSTEM_PROMPT`, invokes the configured primary model (and optional fallback), then appends its reply to the checkpoint. The API service persists the same user/assistant transcript and run record outside the graph.

There is intentionally no pre-validation, memory-loading node, `ToolNode`, router, or `interrupt()` in this phase. SSE is an API presentation of token events from this same Agent node, not an additional graph node. The model may ask its own clarifying questions using the system prompt and conversation history.

### Single-Agent evolution rules

All later milestones preserve the graph above. The implementation may extend the Agent system prompt and pass bounded, server-owned runtime context such as confirmed preferences, locale, or a prepared itinerary draft, but it must not add graph nodes, conditional edges, `ToolNode`, `Send`, or a multi-Agent supervisor.

Messages, run records, preferences, confirmations, and future itinerary versions remain application-owned data. Their APIs and services perform authorization, validation, auditing, and persistence before or after the one Agent invocation. A model proposal is never treated as a confirmed preference or an irreversible action.

### Human confirmation

Preference writes, itinerary exports, sharing links, and any future booking action require explicit API-level confirmation. The confirmation state is persisted by application services; it does not use a LangGraph `interrupt()` node. No irreversible side effect occurs before confirmation.

## 8. API design (v1)

The complete request, response, streaming, identity, and concurrency contract lives in [Conversation API and identity contract](conversation-api-design.md). The API follows the stable OpenAI **Responses** vocabulary: a new `input` message produces one `response` with typed `output` items, and a stream contains ordered `response.*` events. Its DTOs cover text, image, file, function tool definitions, function calls, and function outputs; execution remains deliberately text-only and tool-free in this single-Agent phase. The application-owned `conversation` reference binds that response to durable history.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness probe |
| `GET` | `/health/ready` | Database and required dependency readiness probe |
| `POST` | `/api/v1/conversations` | Create a conversation and assign a `thread_id` |
| `GET` | `/api/v1/conversations` | List the current user's conversations with pagination |
| `GET` | `/api/v1/conversations/{id}` | Retrieve a conversation and messages |
| `POST` | `/api/v1/conversations/{id}/messages` | Submit a message and return JSON or an SSE stream |
| `GET` | `/api/v1/preferences` | Read confirmed preferences |
| `PUT` | `/api/v1/preferences` | Explicitly update preferences |

The text stream emits `response.created`, `response.in_progress`, `response.output_item.added`, `response.content_part.added`, `response.output_text.delta`, and terminal `response.completed` events. Each event includes an increasing `sequence_number`; output events have a stable persisted `item_id`. A failed run emits `response.failed` followed by `error`. Streaming and non-streaming responses use the same domain execution result rather than separate Agent implementations.

Schema ownership is deliberately split: `schemas/responses.py` contains the broad Responses-inspired protocol (multimodal parts, tool definitions, function calls, output items, and stream events); `schemas/conversation_requests.py` contains the narrower authenticated HTTP input DTO; and `schemas/messages.py` contains persistence DTOs. A route must not accept a protocol-only capability merely because the protocol can represent it.

Errors follow a Problem Details-like shape with `code`, `message`, `request_id`, and optional safe-to-display `details`. Provider secrets, full stack traces, and unfiltered tool output are never returned to clients.

## 9. Travel-tool boundary

| Tool | Initial capability | Constraints |
| --- | --- | --- |
| `get_weather` | Retrieve destination weather and forecast | City normalization, timeout, and retrieval timestamp |
| `search_attractions` | Search attractions by city, weather, and preferences | Allowlisted providers, source URL, deduplication, and result limit |
| `get_destination_facts` | Retrieve opening hours, transit, or safety notices | Phase two; sources and freshness are mandatory |
| `build_itinerary` | Build an itinerary draft from verified data | Pure computation; no external side effect |
| `save_preference` | Save a confirmed preference | Explicit user confirmation and audit event required |

Tool inputs and outputs use Pydantic schemas. Every external call has connection and read timeouts, bounded retries, rate limits, and a cache policy. Volatile information such as weather and opening hours must display retrieval time; the model must not present search results as guarantees.

## 10. Security, reliability, and operations

### Security

- Require the authenticated local account; do not support anonymous conversations. JWT access tokens identify the user and request context carries that `user_id`; never infer it from model text.
- Use short-lived JWT access tokens and rotating refresh tokens. Validate issuer, audience, expiration, subject, and token ID; persist revocation and user-disable state. The first release owns password login and uses Argon2id password hashes; an external OIDC provider remains a future integration option.
- Enforce an ownership check before resolving a `conversation_id` to a `thread_id`. A valid token alone never authorizes a conversation.
- Serialize active runs for each conversation and accept an `Idempotency-Key` for message submissions so retries cannot duplicate agent or tool execution.
- Limit requests and concurrent streams by user and IP. Apply per-run tool-call counts, total duration, and cost budgets.
- Use `.env` only for local development. Production secrets come from a secret manager. Redact secrets and personal data from logs, traces, and audit records.
- Enforce user isolation in conversation reads, checkpoints, preference retrieval, cache keys, and evaluation datasets.

### Reliability

- The LLM service owns model configuration, total timeout budget, exponential backoff, and configurable fallback models. Business nodes do not construct provider clients directly.
- Retry transient network failures a bounded number of times; return LLM-recoverable tool errors to the graph; request user input for missing information; alert on unexpected errors and return a traceable request ID.
- Use idempotency keys for external writes. Future exports and bookings require audit records and confirmation.

### Observability and quality

- Every log line includes `request_id`, redacted `user_id`, `conversation_id`, `thread_id`, `run_id`, and trace ID.
- Core metrics: request volume, latency, error rate, time to first token, completion time, model usage and cost, rate-limit events, and stream completion.
- Retain a trace for every Agent run. LangSmith is recommended for the first release. If the team already uses Langfuse, use an observability adapter so business code remains vendor-neutral.
- Maintain Chinese travel-query evaluation data under `evals/`, covering weather consistency, source citations, constraint adherence, clarification quality, tool-failure recovery, and safety boundaries.

## 11. Deployment and environments

- Local: Docker Compose starts PostgreSQL and later Redis or Valkey; Prometheus and Grafana are optional.
- Test: use an isolated database and secrets, apply migrations, then run unit, integration, API, and evaluation smoke tests.
- Production: containerize the service, run Alembic migrations once, and run multiple API replicas. System-management data and LangGraph checkpoints live in PostgreSQL; session and checkpoint storage are never held only in process memory.
- Configure environments through environment variables. `.env.example` lists safe placeholders only; development, test, and production use separate values.

## 12. Release acceptance criteria

The first production candidate must satisfy all of the following:

- Multi-turn travel advice works through protected v1 APIs with SSE streaming; all conversations belong to the authenticated local user.
- A conversation can resume its LangGraph state after a process restart.
- Weather and attraction tools have schemas, timeouts, failure handling, and sources with retrieval times.
- Every request has correlated logs, basic metrics, and an Agent trace.
- Database migrations, tests, code checks, and a minimum evaluation run in CI.
- No real secret is committed; user data, cache, and memory are isolated by identity.

## 13. References

- [fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template): reference for project layering, persistence, observability, and operations.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): basis for thread, checkpoint, and persistence design.
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview): state graphs, nodes, and conditional routing.
