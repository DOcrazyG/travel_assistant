# Travel Assistant Backend Iteration Plan

**Status:** P0 complete; P1 foundation complete; P2.0 non-streaming Agent loop in progress
**Related design:** [Travel Assistant Backend Architecture Design](architecture-design.md)  
**Planning approach:** Deliver milestones with explicit acceptance criteria. Expand scope only after the preceding milestone is complete.

## 0. Delivery sequence

```mermaid
flowchart LR
    P0[P0 Engineering baseline] --> P1[P1 API and data foundation]
    P1 --> P2[P2 Stateful Agent]
    P2 --> P3[P3 Production safeguards]
    P3 --> P4[P4 Travel capabilities]
    P4 --> P5[P5 Release and continuous improvement]
```

| Priority | Milestone | Goal | Prerequisites |
| --- | --- | --- | --- |
| P0 | Engineering baseline | Repeatable installation, startup, and testing | None |
| P1 | API and data foundation | Callable service with persistent conversations | P0 |
| P2 | LangGraph travel loop | Multi-turn tool use and streaming conversations | P1 |
| P3 | Production safeguards | Security, observability, reliability, and evaluation | P1, P2 |
| P4 | Domain capabilities | Preferences, itineraries, retrieval, and human confirmation | P2, P3 |
| P5 | Release and operations | Deployable, recoverable, continuously improved service | P3, P4 |

## P0: Engineering baseline

**Goal:** Establish a maintainable backend foundation without implementing travel business logic.

- [x] Create the `app/`, `tests/`, `docs/`, `scripts/`, and `alembic/` skeleton.
- [x] Add a FastAPI application factory, typed settings, and `/health/live` and `/health/ready` probes.
- [x] Move dependencies to `pyproject.toml`: FastAPI, Uvicorn, Pydantic Settings, LangChain 1.x, LangGraph 1.x, database tooling, and test tooling.
- [x] Standardize development commands through `uv` and `Makefile`: installation, formatting, static checks, tests, startup, and future migrations.
- [x] Complete `.env.example` with safe placeholders and ensure local environment files are ignored.
- [x] Configure Ruff, Pyright, pytest, pre-commit, and base CI.
- [x] Add unit tests for FastAPI health checks. Travel tools will receive their own tests when they are implemented in P2.

**Acceptance criteria:** A new developer can start the health-check service using only the README and `.env.example`; CI runs linting, type checking, and tests.

## P1: API, data, and access control

**Goal:** Provide stable conversation APIs and persistence boundaries before complex Agent behavior.

- [x] Design Pydantic request and response schemas plus a unified error format.
- [x] Build `api/v1` routes for health checks, conversation creation and retrieval, message retrieval, and message submission. Message submission invokes the P2 Agent execution flow; streaming and resume remain P2 work.
- [x] Add PostgreSQL, SQLModel/SQLAlchemy, and Alembic migrations for application-owned identity, conversation, message, run, tool-call, attachment, audit, and future-extension tables. The full schema is defined up front; product capabilities activate incrementally.
- [x] Implement scoped CRUD service layers; route handlers must not construct SQL or call models directly. Conversation persistence remains in `app/services/crud/conversations.py`, without a duplicate repository layer.
- [x] Choose the first identity model: multiple local email/password accounts with JWT; anonymous guest conversations and machine integrations are not supported. Create a public `conversation_id` mapped one-to-one to a stable internal `thread_id` for every conversation.
- [x] Add request IDs, middleware logging context, a CORS allowlist, and base exception handling.
- [x] Add Valkey-backed minimum rate limiting and durable, user-scoped idempotency records. An explicit in-memory rate-limit fallback is allowed only in development.
- [x] Add API integration tests for unauthenticated requests, authorization failures, conversation isolation, pagination, persistence across restart, and error format.

**Acceptance criteria:** Conversations and messages survive an API restart; user A cannot read user B's conversation; all APIs appear in `/docs`.

## P2: LangGraph travel Agent loop

**Goal:** Implement a recoverable graph that replaces a manually managed Agent loop.

- [ ] Define `TravelAgentState`, runtime context, and typed node input/output. Add reducers for messages, tool results, and citations.
- [ ] Assemble `validate → load_memory → agent ↔ tools → compose → persist`. P2.0 has state/context, append-only message history, and a checkpointed non-streaming `validate → load_memory → agent → compose → persist` execution boundary; tools remain pending.
- [ ] Implement weather and attraction tools with LangGraph `ToolNode` and LangChain `@tool` functions.
- [ ] Build an LLM Service for OpenAI-compatible configuration, model registration, call timeouts, retries, and configurable fallback models.
- [ ] Integrate LangGraph `PostgresSaver`; every graph call includes the conversation `thread_id`. Add recovery tests across service restarts.
- [ ] Implement SSE for `POST /messages` with status, token, tool-call, tool-result, final-response, and error events.
- [ ] Add Pydantic parameter validation, connection/read timeouts, bounded retries, tool-call limits, source URLs, and retrieval timestamps to every tool.
- [ ] Ask clarifying questions when destination, dates, or essential constraints are missing. Do not treat a model guess as a user constraint.
- [ ] Add Agent unit and integration tests for normal queries, tool timeout, no-result responses, invalid model output, and conversation recovery.

**Acceptance criteria:** A user can ask follow-up questions in the same conversation; weather and attraction results appear as citations in the final answer; one external-tool failure does not crash the service.

## P3: Production safeguards

**Goal:** Make the service diagnosable, protected, and measurable.

- [ ] Complete deferred account capabilities: email verification, password reset, account lifecycle operations, and security-event review. Registration/login, Argon2id password hashing, JWT validation, refresh-session rotation, revocation, expiration, and security-event logging start in P1.
- [ ] Define rate limits by user and IP, concurrent-stream limits, and LLM/tool duration and cost budgets.
- [ ] Define four failure strategies: retry transient errors, return model-recoverable errors to the graph, clarify user-fixable errors, and alert on unexpected errors.
- [ ] Add structured logs and redaction rules for `request_id`, `conversation_id`, `thread_id`, `run_id`, and trace IDs.
- [ ] Add Prometheus metrics and Grafana dashboards for latency, errors, tool success, token and cost usage, rate limits, interruptions, and resumes.
- [ ] Add LangSmith traces. If the team uses Langfuse, introduce it through an adapter and keep business code vendor-neutral.
- [ ] Create `evals/` with Chinese travel-consultation data and measures for constraint adherence, citations, weather consistency, clarification quality, and recovery from tool failures.
- [ ] Add security tests for secret scanning, prompt-injection samples, authorization bypasses, and tool-parameter abuse.
- [ ] Add Dockerfile, Compose, database backup and restore documentation, and CI image builds.

**Acceptance criteria:** Pass one end-to-end load test and failure drill; a problem can be traced by request, run, and trace ID; evaluation regressions can block a release.

## P4: Travel domain capabilities

**Goal:** Improve personalization and itinerary quality on a reliable foundation.

- [ ] Add `travel_preferences` plus explicit APIs for saving, viewing, changing, deleting, and auditing preferences.
- [ ] Read confirmed preferences in the graph. Store model-extracted preferences as candidates until user confirmation.
- [ ] Select and add a vector store for user-isolated semantic retrieval of confirmed preferences and high-value travel facts.
- [ ] Add destination facts, route/map, transit, and opening-hours tools only after provider review, source rules, cache policy, and tests for each.
- [ ] Implement `build_itinerary` to create structured itinerary drafts using dates, budget, geography, and opening hours.
- [ ] Use LangGraph `Send` only for independent retrieval tasks. Configure reducers, concurrency limits, and cost budgets before parallelizing.
- [ ] Require `interrupt()` confirmation for preference writes, itinerary export, and sharing links. Ensure no non-idempotent side effect runs before confirmation.
- [ ] Support itinerary versions, export, and sharing permissions. Booking and payments remain out of scope.

**Acceptance criteria:** A user explicitly manages preferences; itinerary drafts include constraints, sources, freshness, and actionable daily schedules; confirmation flows resume safely.

## P5: Release and continuous improvement

**Goal:** Establish stable releases and a data-driven improvement loop.

- [ ] Write runbooks for environments, secrets, migrations, rollback, backup, and incident response.
- [ ] Validate releases in staging with anonymized evaluation data.
- [ ] Implement versioned releases, health/readiness probes, automated rollback, and change logs.
- [ ] Build operational dashboards and alerts; routinely review failed tools, low-quality replies, cost, and latency.
- [ ] Create a feedback loop that associates feedback with a specific `run_id`; add only redacted, reviewed feedback to evaluation datasets.
- [ ] Review tool providers, model configuration, privacy-retention periods, and dependency security updates monthly.

**Acceptance criteria:** Complete a staged production-release exercise and a rollback exercise; failures have an owner, alert, and documented recovery process.

## Decisions to confirm before P1

- [x] First identity model: multiple local email/password accounts with JWT; no anonymous conversations or API-key credentials.
- [x] API compatibility target: OpenAI Chat Completions-inspired request/response and streaming semantics, not zero-change OpenAI SDK compatibility.
- [x] Conversation creation: the first chat request creates a conversation automatically; later requests send the returned `conversation_id`.
- [x] Self-managed accounts: open registration with Argon2id password hashes, email login, JWT access tokens, and rotating refresh tokens. Email verification and password reset are deferred to P3.
- [x] Token lifecycle: short-lived access JWTs, rotating refresh sessions, and server-side revocation state.
- [x] Concurrent writes: one active run per conversation plus idempotency keys for submissions.
- [ ] First LLM provider and fallback model. Must arbitrary OpenAI-compatible endpoints remain supported?
- [ ] Deployment target: single-host Docker Compose, managed containers, or Kubernetes?
- [ ] Is live route, traffic, or opening-hours data needed? Which regions and budget limits apply?
- [x] Sensitive data and retention: do not persist identity documents, contact details, or precise locations; store accessibility/dietary preferences only after confirmation. Retain conversations/checkpoints and run/tool audit data for 180 days after last activity; make explicit deletions unavailable immediately and physically purge within 30 days; retain security audit data for 365 days, idempotency records for 24 hours, and backups for 35 days.
- [ ] Observability choice: LangSmith (recommended) or an existing Langfuse installation? Who owns access and cost?
- [ ] Are languages beyond Chinese required? What are the default timezone and currency rules?

## Do not implement prematurely

- [ ] Do not introduce multi-Agent collaboration, complex RAG, or multiple vector databases before P2 is validated.
- [ ] Do not add booking, payment, email sending, or other irreversible actions before identity isolation, auditing, and human confirmation are complete.
- [ ] Do not use subjective examples as the release gate before an evaluation baseline exists.
- [ ] Do not scale concurrency or multi-model fallback before basic metrics and error tracing are complete.
