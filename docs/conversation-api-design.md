# Conversation API and Identity Contract

[中文版本](conversation-api-design.zh-CN.md)

**Status:** Approved contract; P2 single-Agent JSON and SSE execution implemented
**Last updated:** 2026-08-10  
**Applies to:** Authenticated conversational calls, conversation ownership, and LangGraph state recovery

## 1. Intent and scope

The service exposes a response invocation that feels familiar to an LLM caller while retaining server-owned conversation state. It adopts the useful parts of the stable OpenAI Responses convention:

- request fields such as `model`, `input`, and `stream`;
- a response object with `id`, `object`, `created_at`, `status`, `output`, and `usage`;
- ordered incremental text in `response.output_text.delta` events.

This is an **inspired contract**, not a promise that an unmodified OpenAI Python SDK or every OpenAI request option will work. The service adds a durable `conversation` reference. Its protocol DTOs define text, image, file, and function-call records, while the public conversation request DTO exposes one user input and the current single-Agent runtime enables only text input/output.

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

For every request that carries a `conversation_id`, including streams, the service verifies:

```text
authenticated credential → active user → conversation `user_id` match → thread lookup → execution
```

Failure returns `401` for missing, invalid, expired, or revoked credentials. A request whose user does not own the conversation receives `404` to avoid confirming that the resource exists.

## 4. Response invocation contract

### Endpoint

```text
POST /api/v1/conversations/{conversation_id}/messages
Authorization: Bearer <access-token>
Idempotency-Key: <opaque-client-generated-key>  # required for a message submission
Content-Type: application/json
```

`Idempotency-Key` is unique per method and route for the sole authenticated user, together with the request body fingerprint. Replaying the same key and body returns the original accepted result/run; replaying it with a different body returns `409`. Keys have a finite retention period configured with the idempotency store.

### Request

```json
{
  "model": "travel-assistant",
  "input": {
    "type": "message",
    "role": "user",
    "content": [
      {"type": "input_text", "text": "请安排上海三日游"}
    ]
  },
  "stream": false,
  "metadata": {"locale": "zh-CN", "timezone": "Asia/Shanghai"}
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `model` | yes | An application model alias, not necessarily a provider model name. |
| `input` | yes | One new user message for this turn. Its content is a non-empty list of `input_text`, `input_image`, or `input_file` parts. Image and file values are type-supported but return `input_content_not_supported` until a provider-neutral multimodal adapter is delivered. |
| `stream` | no | Defaults to `false`; `true` returns `text/event-stream`. |
| `metadata` | no | Small, validated request context such as locale/timezone. It is not an authorization channel and must not contain secrets or unbounded personal data. |

The caller sends only the new input for the current turn. It must not resend the entire prior transcript. The service loads the canonical history and LangGraph checkpoint using the mapped `thread_id`, appends input once, and controls system prompts itself. Future tool turns use `function_call` output items and matching `function_call_output` input items. Those are protocol-level records; tool selection and execution remain server-owned rather than client request fields.

### Type ownership

`app.schemas.responses` is the broad protocol type system, modeled after the OpenAI Responses resource. `app.schemas.conversation_requests` is the request boundary for this endpoint and accepts only one user message. `app.schemas.messages` is the independent durable-transcript schema. This distinction prevents a future protocol addition from becoming a public capability before its authorization, execution, and persistence rules exist.

### Non-streaming response

```json
{
  "id": "019...",
  "object": "response",
  "created_at": 1786358400,
  "model": "travel-assistant",
  "status": "completed",
  "output": [
    {
      "id": "019...",
      "type": "message",
      "role": "assistant",
      "status": "completed",
      "content": [
        {"type": "output_text", "text": "可以，先确认你的出行日期……", "annotations": []}
      ]
    }
  ],
  "conversation": {"id": "019...", "object": "conversation"},
  "usage": null
}
```

`usage` is present when provider accounting is available. The response ID is the application Agent-run ID; each output item's ID is the durable assistant-message ID.

### Streaming response

The stream uses SSE and follows the Responses event naming convention. Each payload contains its `type` and a strictly increasing `sequence_number`; item and content events also carry the stable assistant `item_id`.

| SSE event | Payload intent |
| --- | --- |
| `response.created` / `response.in_progress` | Response envelope and active lifecycle state |
| `response.output_item.added` | Durable in-progress assistant message item |
| `response.content_part.added` | Empty `output_text` part created for that message |
| `response.output_text.delta` | Incremental rendered text |
| `response.output_text.done`, `response.content_part.done`, `response.output_item.done` | Finalized nested content and item |
| `response.completed` | Final response envelope with complete output |
| `response.failed` | Terminal failed response envelope |
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

The chat endpoint and REST endpoint invoke the same conversation service. They must not implement separate history, authorization, or persistence rules.

## 6. Concurrency, retries, and execution lifecycle

At most one active Agent run is permitted for a `conversation_id`. A second non-idempotent message while a run is active receives `409` with code `conversation_busy` and the active `run_id`; clients can wait for the stream to finish and retry with a new idempotency key. This prevents two runs from reading the same checkpoint and writing divergent state.

Runs use explicit states: `queued`, `running`, `completed`, `failed`, and `cancelled`. Retrying an HTTP request is not the same as starting a second run.

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
- Conversations are created explicitly before message submission.
- Follow stable OpenAI Responses-style request, response, and streaming conventions without claiming drop-in SDK compatibility.
- One active run per conversation and idempotency protection for submissions.
- Retention periods are 180 days for conversation/checkpoint/run data, 365 days for security audit data, 24 hours for idempotency records, and 35 days for backups; explicit deletion is immediately effective and purged within 30 days.
