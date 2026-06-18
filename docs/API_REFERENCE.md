# API reference — AI Co-Pilot for SaaS Analytics Platform

Base URL (local dev): `http://localhost:6001`

All endpoints except `/api/auth/login` require `Authorization: Bearer <jwt>`.

## Auth

### `POST /api/auth/login`

Request:
```json
{ "email": "user@tenant.com", "password": "..." }
```

Response `200`:
```json
{ "access_token": "...", "token_type": "bearer", "expires_in": 1800 }
```
A refresh token is set as an httpOnly cookie; it is not returned in the body.

### `POST /api/auth/refresh`

Reads the refresh cookie, returns a new access token in the same shape as login. `401` if the refresh token is missing, expired, or revoked.

## Co-pilot

### `POST /api/copilot/query`

Streams a Server-Sent Events response.

Request:
```json
{
  "query": "How did MRR trend over the last two quarters?",
  "conversation_id": "conv_8a1c"
}
```

`conversation_id` is optional; omit it to start a new conversation.

Response: `Content-Type: text/event-stream`. Event types:

| Event | Payload | Meaning |
|---|---|---|
| `message_start` | `{ "conversation_id": "..." }` | Stream opened, conversation id assigned if new |
| `content_block_delta` | `{ "text": "..." }` | One chunk of the model's answer |
| `tool_call` | `{ "name": "get_metric_trend", "args": {...} }` | Informational: a tool is being invoked (useful for a "thinking" indicator in the UI) |
| `tool_result` | `{ "name": "get_metric_trend", "summary": "..." }` | Informational: tool finished; summary is safe to show, not raw rows |
| `chart_data` | `{ "type": "line", "series": [...] }` | Structured data for the frontend to render a chart, when applicable |
| `message_stop` | `{}` | Stream complete |
| `error` | `{ "code": "...", "message": "..." }` | Something failed; stream ends after this event |

Error codes: `unauthorized` (401), `forbidden_role` (403), `forbidden_tenant` (403), `injection_flagged` (400), `validation_error` (400), `upstream_error` (502), `rate_limited` (429).

## Analytics tool schemas (sent to Anthropic as tool definitions)

```json
{
  "name": "get_metric_trend",
  "description": "Return a time series for one SaaS metric over a date range.",
  "input_schema": {
    "type": "object",
    "properties": {
      "metric": { "type": "string", "enum": ["mrr", "arr", "active_users", "new_signups"] },
      "start_date": { "type": "string", "format": "date" },
      "end_date": { "type": "string", "format": "date" },
      "granularity": { "type": "string", "enum": ["day", "week", "month"] }
    },
    "required": ["metric", "start_date", "end_date", "granularity"]
  }
}
```

```json
{
  "name": "get_churn_rate",
  "description": "Return churn rate for a given period.",
  "input_schema": {
    "type": "object",
    "properties": {
      "period": { "type": "string", "enum": ["last_month", "last_quarter", "last_year"] }
    },
    "required": ["period"]
  }
}
```

```json
{
  "name": "compare_segments",
  "description": "Compare a metric between two customer segments. Restricted to analyst/admin roles.",
  "input_schema": {
    "type": "object",
    "properties": {
      "metric": { "type": "string", "enum": ["mrr", "churn_rate", "active_users"] },
      "segment_a": { "type": "string" },
      "segment_b": { "type": "string" }
    },
    "required": ["metric", "segment_a", "segment_b"]
  }
}
```

```json
{
  "name": "get_top_customers",
  "description": "List top customers by a metric. Restricted to analyst/admin roles.",
  "input_schema": {
    "type": "object",
    "properties": {
      "sort_by": { "type": "string", "enum": ["mrr", "usage"] },
      "limit": { "type": "integer", "minimum": 1, "maximum": 25 }
    },
    "required": ["sort_by", "limit"]
  }
}
```

```json
{
  "name": "list_active_alerts",
  "description": "List currently active billing/usage anomaly alerts. Admin only.",
  "input_schema": { "type": "object", "properties": {} }
}
```

Note: every one of these schemas is mirrored by a Pydantic model in `backend/app/validator/query_validator.py` — the JSON schema above constrains what the model can *propose*, the Pydantic model is what the backend actually *trusts*.

## Rate limiting

`POST /api/copilot/query` is rate-limited per user (suggested default: 20 requests/minute) using `slowapi`. Exceeding the limit returns `429` with a `Retry-After` header.
