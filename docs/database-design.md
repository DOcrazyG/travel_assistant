# Travel Assistant Database Design

**Status:** Multi-account SQLModel definitions and rebuildable initial Alembic baseline
**Last updated:** 2026-08-11
**Database:** PostgreSQL 16; MinIO stores attachment bytes; LangGraph owns its checkpoint tables

## Scope

This is a locally authenticated, multi-account question-answering application. It has local accounts but no organizations, workspaces, roles, service principals, API keys, or cross-user sharing. `app` is owned by the application; LangGraph checkpoint tables remain dependency-owned in a separate `langgraph` schema.

All IDs are application-generated UUIDv7 values. All timestamps are UTC `timestamptz`. Foreign keys use PostgreSQL's default `RESTRICT` behavior, so a purge worker must intentionally remove dependent rows in a safe order.

## Core invariants

- Every user-owned resource has a direct `user_id → users.id` foreign key; there are no tenant IDs, principals, memberships, or composite tenant keys.
- A conversation has a public `id` and an immutable, globally unique LangGraph `thread_id`. The application authorizes all requests against its `user_id`.
- Message sequence is positive and unique inside its conversation. Inserting a message, incrementing `latest_message_sequence`, and updating `last_message_at` must be one transaction.
- At most one `queued`, `running`, or `interrupted` Agent run exists for a conversation.
- Soft deletion is explicit: conversations and users require their `deleted` status to agree with `deleted_at`; attachments require the same agreement with `upload_status = 'deleted'`.

## Tables

### Identity and authentication

`users` is the only account table. It has UUIDv7 `id`; `email` and lowercase `email_normalized`; Argon2id `password_hash`; status (`pending_verification`, `active`, `disabled`, `deleted`); an explicit `is_admin` bootstrap marker; authentication lifecycle timestamps; and normal creation/update/deletion timestamps. Constraints enforce the lowercase and deletion-state rules. Partial unique indexes permit one non-deleted account for each normalized email and one non-deleted administrator; an initial migration removes the retired single-account index.

`auth_sessions` represents a revocable refresh-token family. It has `id`, direct `user_id`, unique `token_family_id`, expiry/revocation timestamps, and bounded device metadata. Its indexes are `(user_id, expires_at) WHERE revoked_at IS NULL` and `expires_at`.

`refresh_tokens` stores one hash per rotation: `id`, `session_id`, unique `token_hash`, issue/expiry/consume/revoke timestamps, and nullable `replaced_by_id`. It indexes `(session_id, issued_at)` and `expires_at`.

`revoked_access_tokens` contains JWT `jti` (PK), `user_id`, `expires_at`, `revoked_at`, and `reason`; `expires_at` supports cleanup.

`auth_one_time_tokens` contains `id`, `user_id`, purpose (`email_verify` or `password_reset`), unique token hash, expiry/consumption timestamps, request IP hash, and user agent. It indexes `(user_id, purpose, created_at)` and expiry.

### Conversations and messages

`conversations` contains `id`, direct `user_id`, unique `thread_id`, title and `title_source` (`system`, `user`, or null), status (`active`, `archived`, `deleted`), JSONB `metadata`, message ordering fields, optimistic `version`, and archive/delete/purge timestamps.

- `(user_id, last_message_at DESC, id DESC) WHERE deleted_at IS NULL` supports the history list and cursor pagination.
- `(status, last_message_at DESC) WHERE deleted_at IS NULL` supports housekeeping.
- `purge_after_at WHERE deleted_at IS NOT NULL` serves the deletion worker.

`messages` is the canonical ordered transcript: `id`, `conversation_id`, positive `sequence`, role (`user`, `assistant`, `system`, `tool`), JSONB content array, rendering projection, content status, optional `agent_run_id`, model provenance, token count, and lifecycle timestamps. `UNIQUE (conversation_id, sequence)` prevents duplicate ordinals. Its primary retrieval index is `(conversation_id, sequence) WHERE deleted_at IS NULL`; Agent-run inspection uses a partial `agent_run_id` index.

`message_citations` stores a sanitized source for an answer: `id`, `message_id`, non-negative position, provider/source metadata, URL, bounded snippet, and retrieval/publication timestamps. `(message_id, position)` is unique.

### Agent execution

`agent_runs` is one accepted graph invocation. It stores `id`, `conversation_id`, run status, requested/resolved model identifiers, bounded request metadata, trace ID, usage/cost, timing, redacted error data, interrupt payload, and creation/update times. A partial unique index on `conversation_id` covers active statuses; history, monitoring, and terminal retention have dedicated indexes.

`tool_calls` is a redacted child audit record with `id`, `agent_run_id`, positive per-run sequence, tool/provider IDs, status, redacted input/output summaries, source URLs, timing, duration, and safe error fields. `(agent_run_id, sequence)` is unique; worker and tool-history indexes support its query paths.

`idempotency_keys` makes a retry of a mutation safe. It stores method, route, opaque key, body fingerprint, optional produced conversation/run IDs, status, response snapshot, and expiry. Before multi-user message submissions are enabled, its unique scope must be migrated to include a direct `user_id`; the present key is a single-account baseline artifact.

### Attachments and preferences

`attachments` stores MinIO metadata only: direct `user_id`, immutable object location, sanitized filename/MIME type, size/hash, type, upload/scan/processing state, and lifecycle timestamps. Object location is unique. Size/state/deletion checks and upload/scan/user worker indexes protect normal operations. `message_attachments` makes an attachment single-use through unique `attachment_id`, with composite PK `(message_id, attachment_id)` and unique per-message position.

`travel_preferences` stores confirmed user-managed long-term values: `id`, direct `user_id`, category, JSONB value, optional source message, status, confirmation/expiry timestamps, and soft-delete timestamp. Only one confirmed, non-deleted category may exist for the user.

### Audit and deletion

`security_audit_events` is append-only: identity `id`, optional `user_id`, event type/outcome, request/device metadata, redacted JSONB details, and occurrence time. It indexes user, event type, request ID, and time.

`data_deletion_requests` is the durable, retryable purge queue: `id`, optional requesting user, target type (`conversation`, `user`, `attachment`), target ID, reason, status, scheduling/execution timestamps, and bounded failure details. It indexes due jobs, target lookup, and completed jobs. Explicit conversation deletion immediately sets its deletion timestamp and schedules physical cleanup after 30 days; retention may schedule inactive conversations after 180 days.

## Retention and migration policy

Business records are hidden by soft deletion first. The worker then cancels an active run, deletes MinIO objects, removes citation/attachment/tool/message/run children, removes the LangGraph checkpoint through its supported lifecycle, deletes the conversation, and completes the deletion request. Failures remain retryable and auditable.

The initial migration intentionally rebuilds the whole `app` schema. Its downgrade uses `DROP SCHEMA ... CASCADE` and is destructive. Future model changes require a new reviewed Alembic revision; do not edit this baseline once it has been deployed.
