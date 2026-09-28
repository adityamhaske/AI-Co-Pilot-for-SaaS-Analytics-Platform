# API reference — AI Co-Pilot for SaaS Analytics Platform

Base URL (local dev): `http://localhost:6001`. Outside production, the generated OpenAPI
docs are served at `/docs` and are the authority on field-level detail.

Every endpoint under `/api` requires `Authorization: Bearer <access token>`, except
`POST /api/auth/login`, which takes credentials, and `POST /api/auth/refresh` and
`/logout`, which read the refresh cookie. A refresh token presented as a bearer token is
rejected: bearer tokens must carry `typ: access`.

Errors use FastAPI's shape, `{ "detail": "..." }`. A request body that fails validation
is a `422`. Rate limiting is the exception to both; see [Rate limiting](#rate-limiting).

## Auth

### `POST /api/auth/login`

Request:
```json
{ "email": "admin@test.com", "password": "..." }
```

Response `200`:
```json
{ "access_token": "...", "token_type": "bearer", "expires_in": 900 }
```

`expires_in` is in seconds: `ACCESS_TOKEN_TTL_MINUTES` × 60, fifteen minutes by default. The refresh token is set as
the `refresh_token` cookie — httpOnly, `Secure`, `SameSite=Lax` — and is never returned
in the body. A wrong email and a wrong password both return the same `401`, in the same
time.

### `POST /api/auth/refresh`

Reads the refresh cookie and returns a new access token in the same shape as login. The
cookie is rotated on every call; presenting an already-rotated refresh token revokes every
refresh token the user holds. `401` if the cookie is missing, expired or revoked, or if the
user's role or tenant has changed since it was issued.

### `POST /api/auth/logout`

Revokes the user's refresh tokens and clears the cookie. Returns
`{ "status": "logged_out" }`, including when there was no cookie to revoke.

### `GET /api/auth/me`

```json
{ "id": "...", "email": "admin@test.com", "role": "admin", "tenant_id": "..." }
```

## Co-pilot

### `POST /api/copilot/query`

Streams one answer as Server-Sent Events.

Request:
```json
{
  "message": "How did MRR trend over the last two quarters?",
  "conversation_id": "..."
}
```

`message` is 1–4,000 characters. `conversation_id` is optional; omit it to start a new
conversation. Either way, the conversation's id is returned in the `X-Conversation-Id`
response header.

Refused before the stream opens:

| Status | When |
|---|---|
| `400` | The message was flagged by the prompt-injection guard |
| `401` | Missing, invalid or expired access token |
| `403` | The caller's role may not use this endpoint |
| `404` | `conversation_id` does not exist, or belongs to another user — the two are indistinguishable on purpose |
| `422` | The body failed validation, e.g. an empty `message` |
| `429` | The rate limit, or the user's daily cost ceiling (`"Daily usage limit reached. Try again tomorrow."`) |

Otherwise the response is `200` with `Content-Type: text/event-stream`. Each event is one
`data:` line holding a JSON object with a `type`, and the stream always ends with
`data: [DONE]`:

| `type` | Payload | Meaning |
|---|---|---|
| `token` | `{ "text": "..." }` | One chunk of the answer |
| `tool_call` | `{ "name": "get_metric_trend" }` | The model has started a tool call |
| `tool_result` | `{ "name": "...", "input": {...}, "data": ... }` | The call's arguments and the rows it returned, so a figure can be checked rather than taken on trust |
| `usage` | `{ "provider": "...", "model": "...", "input_tokens": 0, "output_tokens": 0 }` | Once per turn, unless the turn ended in a `provider` or `internal` error |
| `error` | `{ "kind": "...", "message": "..." }` | The turn ended early. `provider` errors also carry `retryable` |

`message` is written for display and never carries exception detail. `kind` says what
happened, which matters because the two pairs mean opposite things:

| `kind` | Cause | What is on screen |
|---|---|---|
| `step_limit` | The model used all `MAX_AGENT_STEPS` tool-calling steps | A real, partial answer — render as a warning |
| `timeout` | `AGENT_TIMEOUT_SECONDS` elapsed between steps | A real, partial answer — render as a warning |
| `provider` | The model vendor failed. `retryable: false` for a settled failure — bad key, exhausted quota, unknown model — that asking again will not fix | Usually nothing |
| `internal` | Anything else | Usually nothing |

## Conversations

A caller only ever sees their own conversations. Another user's id returns `404`, never
`403`, so its existence is not confirmed.

| Endpoint | Returns |
|---|---|
| `GET /api/conversations` | Summaries: `id`, `title`, `created_at`, `updated_at`, `message_count` |
| `GET /api/conversations/{id}` | The summary plus `messages`: `id`, `role`, `content`, `created_at`, and `tools` — each tool call's `name`, `input` and `data` |
| `PATCH /api/conversations/{id}` | Renames it. Body `{ "title": "..." }`, 1–200 characters; returns the summary |
| `DELETE /api/conversations/{id}` | `204` |

## Overview

### `GET /api/overview`

The metric strip beside the chat, computed from the same registry the agent uses so the
two cannot disagree. Metrics the caller's role may not read are omitted, not zeroed.

```json
{
  "tiles": [
    { "metric": "mrr", "label": "MRR", "unit": "currency_usd", "value": 7910.79,
      "delta": 0.0, "spark": [10617.89, 10617.89, 10617.89, 7910.79, 7910.79, 7910.79] },
    { "metric": "churn_rate", "label": "Churn", "unit": "ratio", "value": 0.0,
      "delta": null, "spark": [0.1667, 0.0, 0.0, 0.2, 0.0, 0.0] }
  ],
  "generated_at": "2026-09-28T16:05:40.726149Z",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "spend_today_usd": 0.0,
  "daily_limit_usd": 2.0
}
```

Two of the four tiles, from the seeded demo data. `delta` is the fractional change on
the previous month, and `null` when that month was zero, since there is no baseline to
compare against. `spark` is the last six months, oldest first.

## Operations

| Endpoint | Purpose | Responses |
|---|---|---|
| `GET /health` | Liveness. Never touches the database, so a database blip does not get a healthy process restarted | `200 { "status": "ok" }` |
| `GET /ready` | Readiness. Point load-balancer and readiness probes here | `200 { "status": "ready", "database": "ok" }`, or `503 { "status": "degraded", "database": "unreachable" }` |

## Tools the model can call

The model never writes SQL. It is offered these tools, and only those the caller's role
permits:

| Tool | Roles | Arguments |
|---|---|---|
| `get_metric_trend` | viewer, analyst, admin | `metric`, `start_date` and `end_date` (ISO dates), `granularity` (`day`, `week`, `month`) |
| `get_metric_value` | viewer, analyst, admin | `metric`, `period` (`last_month`, `last_quarter`, `last_year`) |
| `compare_segments` | analyst, admin | `metric`, `segment_a`, `segment_b`; optional `period` |
| `get_top_customers` | analyst, admin | `sort_by` (`mrr`, `usage`), `limit` (1–25) |
| `list_active_alerts` | admin | none |

The three metric tools' schemas are generated from the definitions in
[`backend/app/metrics/definitions/`](../../backend/app/metrics/definitions): each tool's
`metric` enum lists only the metrics that support that query shape *and* that the role may
read under the metric's `minimum_role`. Today that is `active_users`, `arr`, `mrr` and
`new_signups` for trends, plus `churn_rate` for single values and comparisons — but the
definitions, not this page, are the source of truth. To print exactly what a role is sent:

```bash
cd backend
ENVIRONMENT=test PYTHONPATH=. python -c \
  'import json; from app.orchestrator import tools; print(json.dumps(tools.schemas_for("viewer"), indent=2))'
```

The schema only bounds what the model can *propose*. At execution the call is checked
again: `app/streaming/sse.py` re-checks the tool against the caller's role, the arguments
are validated by Pydantic models (`app/metrics/queries.py`, `app/orchestrator/bespoke_tools.py`),
and the metric's `minimum_role` is enforced a second time. A rejected call is reported to
the model as a tool error so it can correct itself; the query never runs.

## Rate limiting

| Endpoint | Limit |
|---|---|
| `POST /api/auth/login` | 5 per minute |
| `POST /api/auth/refresh` | 30 per minute |
| `POST /api/copilot/query` | 10 per minute, plus the per-user daily cost ceiling (`DAILY_COST_LIMIT_USD`) |

Exceeding a limit returns `429` with `{ "error": "Rate limit exceeded: 10 per 1 minute" }`.
No `Retry-After` header is sent.

Limits are keyed by client IP address and counted in each server process's memory. The
production image runs four gunicorn workers, so a client can make up to four times the
figures above; see [SECURITY.md](../../SECURITY.md#known-limitations).
