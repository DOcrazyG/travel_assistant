# Conversation API and Identity Contract

**Status:** Approved design for P1; implementation pending
**Last updated:** 2026-08-10  
**Applies to:** Authenticated conversational calls, conversation ownership, and LangGraph state recovery

## 1. Intent and scope

The service exposes a chat invocation that feels familiar to an LLM caller while retaining server-owned conversation state. It adopts the useful parts of the OpenAI Chat Completions convention:

- request fields such as `model`, `messages`, and `stream`;
- a completion response with `id`, `object`, `created`, `choices`, and `usage`;
- incremental text in an OpenAI-shaped `chat.completion.chunk` payload.

This is an **inspired contract**, not a promise that an unmodified OpenAI Python SDK or every OpenAI request option will work. The service has application-specific fields and events, including `conversation_id`, tool progress, interruptions, and citations.

The first release supports only authenticated users. There are no anonymous or guest conversations.

## 2. Identifier and ownership model

| Identifier | Created by | Visibility | Purpose |
| --- | --- | --- | --- |
| `user_id` | identity layer | request context only | The authenticated local user |
| `conversation_id` | application | returned to caller | Unguessable public identifier for one conversation |
| `thread_id` | application | internal only | Stable LangGraph checkpoint sequence for that conversation |
| `run_id` | application | returned to caller | One invocation of the Agent graph |
| `request_id` | middleware | response, logs, events | Correlates one HTTP request across services |

`conversation_id` and `thread_id` have a one-to-one immutable mapping. The API resolves the public ID to the internal ID only after an ownership check. `thread_id` is always supplied to LangGraph's durable PostgreSQL checkpointer; it is neither user identity nor a browser/login session ID.

`conversation_id` must be a high-entropy opaque identifier (for example UUIDv7). It must never be an incrementing database key, a JWT claim, or a client-chosen ID.

## 3. Authentication and credential types

### User access

All user-facing requests use `Authorization: Bearer <access-token>`. The access token is a short-lived JWT, recommended at 15 minutes. The service validates at least `iss`, `aud`, `exp`, `iat`, `sub`, and `jti`, then resolves `sub` to the active local user record.

Access-token expiry alone is insufficient for account disablement and logout. Refresh sessions are persisted and rotated; the associated token ID or session must be revocable. A refresh token is never sent to the Agent, stored in a conversation, or exposed to browser JavaScript when an HttpOnly cookie flow is available.

The initial product owns registration, login, email verification, password reset, and refresh-token rotation. Passwords are hashed with Argon2id and never logged or returned. The service signs its own access JWTs from a tightly managed signing key; a future OIDC integration can replace this issuer behind the same user contract.

### Machine access

Programmatic API-key integrations are out of scope for this release. The only supported credential is a local-user JWT plus its rotating refresh token.

### Authorization rule

For every request that carries a `conversation_id`, including streams and `/resume`, the service verifies:

```text
authenticated credential → active user → conversation `user_id` match → thread lookup → execution
```

Failure returns `401` for missing, invalid, expired, or revoked credentials. A request whose user does not own the conversation receives `404` to avoid confirming that the resource exists.

## 4. Chat invocation contract

### Endpoint

```text
POST /v1/chat/completions
Authorization: Bearer <access-token>
Idempotency-Key: <opaque-client-generated-key>  # required for a message submission
Content-Type: application/json
```

`Idempotency-Key` is unique per method and route for the sole authenticated user, together with the request body fingerprint. Replaying the same key and body returns the original accepted result/run; replaying it with a different body returns `409`. Keys have a finite retention period configured with the idempotency store.

### Request

```json
{
  "model": "travel-assistant",
  "messages": [
    {"role": "user", "content": "请安排上海三日游"}
  ],
  "stream": false,
  "conversation_id": null,
  "metadata": {"locale": "zh-CN", "timezone": "Asia/Shanghai"}
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `model` | yes | An application model alias, not necessarily a provider model name. |
| `messages` | yes | One or more new input messages for this turn. At least one must have `role: "user"`. The first release rejects client-supplied `assistant` and `tool` messages. |
| `stream` | no | Defaults to `false`; `true` returns `text/event-stream`. |
| `conversation_id` | no | Omit or set `null` to create a conversation. Supply the returned value to continue it. |
| `metadata` | no | Small, validated request context such as locale/timezone. It is not an authorization channel and must not contain secrets or unbounded personal data. |

The caller sends only new messages for the current turn. It must not resend the entire prior transcript after a `conversation_id` is established. The service loads the canonical history and LangGraph checkpoint using the mapped `thread_id`, appends validated input once, and controls system prompts and tool messages itself.

### Non-streaming response

```json
{
  "id": "run_01J...",
  "object": "chat.completion",
  "created": 1786358400,
  "model": "travel-assistant",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "可以，先确认你的出行日期……"},
      "finish_reason": "stop"
    }
  ],
  "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
  "travel_assistant": {
    "conversation_id": "conv_01J...",
    "run_id": "run_01J...",
    "request_id": "req_01J...",
    "citations": [],
    "interrupted": false
  }
}
```

`usage` is present when provider accounting is available; values may be omitted or marked provisional while a stream is active. The `travel_assistant` object is the reserved namespace for application extensions and prevents collision with future OpenAI-shaped fields.

### Streaming response

The stream uses SSE. Text deltas are serialized as JSON with `object: "chat.completion.chunk"`; lifecycle, tool, and approval data use named application events. Every event contains `request_id`, `conversation_id`, and `run_id`.

| SSE event | Payload intent |
| --- | --- |
| `meta` | IDs, selected model, and newly created conversation ID |
| `status` | queued, running, or retrying state |
| `token` | An OpenAI-shaped `chat.completion.chunk` text delta |
| `tool_call` / `tool_result` | Redacted progress information, never provider secrets |
| `interrupt` | A durable approval/clarification pause that can later be resumed |
| `final` | Final completion, usage, citations, and completion status |
| `error` | Safe Problem Details-like error payload |

Browser clients should use a `fetch`-based streaming reader so they can send the Bearer authorization header. Native `EventSource` does not provide a suitable standard way to set that header.

## 5. Conversation management endpoints

The REST resource APIs remain available for product UI and management operations:

| Method | Path | Meaning |
| --- | --- | --- |
| `POST` | `/api/v1/conversations` | Explicitly create an empty conversation; optional because first chat can create one. |
| `GET` | `/api/v1/conversations` | List only the authenticated user's conversations. |
| `GET` | `/api/v1/conversations/{conversation_id}` | Return conversation and paginated messages after ownership verification. |
| `DELETE` | `/api/v1/conversations/{conversation_id}` | Make the conversation inaccessible immediately and schedule retention-compliant purge of messages and checkpoints. |
| `POST` | `/api/v1/conversations/{conversation_id}/resume` | Resume a persisted LangGraph interrupt after ownership and run-status validation. |

The chat endpoint and REST endpoint invoke the same conversation service. They must not implement separate history, authorization, or persistence rules.

## 6. Concurrency, retries, and execution lifecycle

At most one active Agent run is permitted for a `conversation_id`. A second non-idempotent message while a run is active receives `409` with code `conversation_busy` and the active `run_id`; clients can wait for the stream to finish and retry with a new idempotency key. This prevents two runs from reading the same checkpoint and writing divergent state.

Runs use explicit states: `queued`, `running`, `interrupted`, `completed`, `failed`, and `cancelled`. An interrupted run keeps its checkpoint and can be resumed only in the same owned conversation. Retrying an HTTP request is not the same as resuming an interrupted run.

All externally observable writes (message insert, run record, tool audit record, and graph persistence boundary) must be designed to be idempotent. External side effects remain prohibited in the first travel-advice release.

## 7. Retention and deletion

The service minimizes stored personal data. Conversation messages, LangGraph checkpoints, run/tool audit records, and confirmed preferences have separate retention categories; deleting a conversation must include its mapped checkpoints and derived summaries according to their category.

An API deletion makes a conversation unavailable immediately, then a background purge removes eligible data and records a minimal deletion audit event. Backups follow their own bounded lifecycle and are not edited in place.

Default retention is 180 days after last activity for conversations, messages, checkpoints, and run/tool audit data; security audit data is retained for 365 days; idempotency records for 24 hours; and backups for 35 days. An explicit deletion makes data unavailable immediately and is physically purged within 30 days, subject to the backup lifecycle. Identity documents, contact details, and precise locations are not persisted in the first release.

## 8. Error and observability contract

Non-streaming errors and SSE `error` events use a safe Problem Details-like payload:

```json
{
  "code": "conversation_busy",
  "message": "A response is already being generated for this conversation.",
  "request_id": "req_01J...",
  "details": {"run_id": "run_01J..."}
}
```

The API never returns provider credentials, raw stack traces, unredacted tool input, or private identifiers. Logs and traces correlate `request_id`, a redacted `user_id`, `conversation_id`, `thread_id`, and `run_id`.

## 9. Decisions recorded

- Authenticated users only; no guest/anonymous conversation mode.
- JWT is the user-facing access credential; use short-lived access tokens, rotating refresh sessions, and revocation state.
- Build first-party registration/login with Argon2id password hashes, email verification, password reset, and rotating refresh tokens; preserve the user boundary for a future OIDC integration.
- The first chat call auto-creates a conversation; subsequent calls provide `conversation_id`.
- Follow OpenAI-style request, response, and streaming conventions without claiming drop-in SDK compatibility.
- One active run per conversation and idempotency protection for submissions.
- Retention periods are 180 days for conversation/checkpoint/run data, 365 days for security audit data, 24 hours for idempotency records, and 35 days for backups; explicit deletion is immediately effective and purged within 30 days.
