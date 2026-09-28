# Changelog

Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is below 1.0.0 the API is not stable and minor versions may break it.

## [Unreleased]

### Added
- **Postgres row-level security** as a second tenant-isolation layer beneath the
  application-side tenant filter, which stays the primary control. Off by default:
  PostgreSQL exempts the table owner, so it only binds when the API connects as a
  separate role — see [SECURITY.md](SECURITY.md). Seven tests try to defeat the policy;
  they skip on SQLite, so CI runs them against Postgres and fails if they skip there.
- **A frontend test suite** (Vitest, Testing Library, jsdom) covering stream parsing,
  formatting and components. The frontend previously had no tests at all.
- First live provider run. The eval suite had never been executed against a real API;
  running it surfaced four adapter bugs that no unit test could have caught, all fixed
  below. Result: 26/26 on 26 golden questions with `gemini-flash-latest`.
- `grade_completion`, which fails any case that ends with an error or an empty answer.
  Added after a run scored 100% while eight cases produced no answer text at all — the
  tool grader passed them because the *call* was correct. A suite that calls that a pass
  is measuring the wrong thing.
- The current date in the system prompt. Without it the model did not know what "now"
  was: asked for "the last 6 months" it guessed a year, got an empty result, guessed
  another, and exhausted its step budget across 2022-2027 without ever answering. This
  was the single largest source of failure in the first run — fixing it took step-limit
  warnings from 8 to 0 and halved p95 latency (14.8s to 7.1s).
- `ToolCall.provider_state`, carrying opaque per-provider data that must round-trip.
  Gemini rejects a replayed function call whose `thought_signature` is missing.
- `AliasChoices` on the API-key and secret settings, so `GOOGLE_API_KEY` and
  `JWT_SECRET_KEY` are accepted alongside the documented names.
- SSE `error` events carry a `kind` — `provider`, `internal`, `step_limit` or
  `timeout` — and still never the exception text. A step limit or timeout leaves a real,
  partial answer on screen, so the UI now renders it as a warning (`role=status`) rather
  than as the failure (`role=alert`) that a vendor outage is.
- Inbound provider tests, feeding SDK-shaped responses through each adapter's
  `stream_turn`. Every bug the first live run found was on the response side, which
  nothing tested; the request side was well covered and correct.

### Changed
- **Replaced `python-jose` with `PyJWT`.** python-jose is effectively unmaintained, and
  its willingness to sign and verify with an empty HMAC key was the mechanism behind the
  0.1.0 token-forgery hole. PyJWT raises `InvalidKeyError` instead. The fail-fast config
  validation stays: it catches short and placeholder secrets, which no library rejects
  for you, and it fails at boot rather than on first login.
- The agent loop now enforces the wall-clock bound the documentation described.
  `agent_timeout_seconds` was declared and never read. Bounds are now explicit and
  separate: `max_agent_steps` for a model that keeps calling tools,
  `agent_timeout_seconds` checked between steps, and `provider_timeout_seconds` handed to
  each SDK to bound a hung HTTP call.
- Gemini's default model is now `gemini-flash-latest`. `gemini-2.5-pro` is rejected for
  new API keys ("no longer available to new users") while still appearing in
  `models.list()` — listing is not proof of access.
- The two prompt-injection eval cases assert on disclosure rather than on a substring.
  Both previously failed a *correct* refusal for quoting the forbidden term back
  ("I cannot present estimated figures as real data" tripped a ban on "estimated").
- Budget tests price against an explicit provider instead of the ambient
  `LLM_PROVIDER`. They hardcoded Anthropic's rates and so failed, correctly priced, for
  anyone whose `.env` selected another provider.
- The eval runner retries a transient vendor failure (rate limit, 5xx, dropped
  connection) twice with backoff, and prints how many cases needed it. A settled one —
  exhausted quota, bad key, missing model — is not retried: waiting does not refill a
  quota, and a genuine failure must not be retried into a pass.

### Fixed
- Gemini reported `stop_reason=other` on every normal completion. The SDK returns an
  enum, so `str()` yields `FinishReason.STOP` rather than `STOP`; `_stop_reason` now
  reads `.name` first.
- The eval runner checked for `ANTHROPIC_API_KEY` regardless of the selected provider.
- **Docker images shipped only the Anthropic SDK**, so an image run with
  `LLM_PROVIDER=gemini` or `openai` started cleanly and failed on the first question.
  `LLM_PROVIDER` is now a build argument, threaded through Compose.
- The CI "Postgres" job was testing SQLite: `conftest.py` ignored `DATABASE_URL`.
  Honouring it surfaced inserts ordered child-before-parent, which SQLite accepted only
  because it ships with foreign keys off. SQLite connections now enforce them.
- `RoleChecker` path matching is exact-or-nested. `startswith` alone let
  `/api/copilot/queryX` satisfy a grant of `/api/copilot/query`.
- The weekly secret scan failed on every run, on a documentation example in
  `OVERHAUL_PLAN.md`: the standard HS256 JWT header, truncated, with no key. It is
  suppressed by fingerprint in `.gitleaksignore`, so a new finding in the same file still
  fails.
- **`/ready` returned `200` when the database was unreachable**, with `"degraded"` only
  in the body. Probes and load balancers act on the status code, so an instance that
  could not serve a single query stayed in rotation — the one thing readiness exists to
  prevent. It now returns `503`.
- The API reference described the pre-0.1.0 API: a `query` request field where the
  server takes `message`, so a client written from it got a `422`; SSE events the server
  never sends; a 20-per-minute per-user limit that is 10 per minute per address; a
  `Retry-After` header that is not sent; and tools and files that no longer exist.
  Rewritten against the code and checked against a running server. The security
  design's RBAC matrix named the removed `get_churn_rate`, and the architecture overview
  now says plainly which parts of the original design it no longer describes.

### Planned
- `/metrics` endpoint and OpenTelemetry traces

## [0.3.0] — 2026-07-29

Conversations, revocable sessions, cost control, and a rebuilt interface.

### Added
- **Conversation persistence and multi-turn context.** Previously every question started
  a fresh context, so a follow-up like "and how does that compare to last year?" had
  nothing to refer back to. `GET/PATCH/DELETE /api/conversations`.
- **Refresh-token revocation.** A signed JWT cannot be withdrawn, so signing out or
  losing a cookie previously left it valid for seven days. Every refresh token now has a
  row, rotates on use, and a replayed rotated token revokes the whole family.
- **Per-user daily cost ceiling**, metered from real token usage. A request-rate limit
  does not bound spend: one request can drive several tool-calling steps.
- `POST /api/auth/logout`, `GET /api/auth/me`, `GET /ready`.
- Structured logging with a request id returned as `X-Request-ID`.
- Production Docker images and a Compose stack with Postgres.
- Root `SECURITY.md` with a disclosure policy and an honest limitations section.

### Changed
- **The interface was rebuilt** on semantic design tokens with a chosen dark theme,
  conversation history grouped by recency, a stop control while streaming, role-filtered
  suggestions, and provenance under every answer.
- Chart colours are now a categorical palette validated for colour-vision separation and
  contrast against both surfaces.
- `/health` is liveness only; readiness moved to `/ready` so a database blip drains an
  instance instead of restarting it.
- CORS narrowed from wildcard methods and headers to the ones actually used.

### Fixed
- The composer's auto-grow measured `scrollHeight` after setting `height: auto` inside a
  flex row, which reports the flex basis — the empty box snapped to its maximum and stuck.
- `datetime.utcnow()` replaced throughout; removed in Python 3.12.
- Tests reset the rate limiter between cases; the login limit was leaking across them.

### Security
- Bearer tokens must carry `typ: access`, so a stolen refresh cookie cannot be replayed
  against the API.
- `/auth/refresh` re-reads the user and rejects stale role or tenant claims.
- Login and refresh are rate limited; password-check timing is equalised for unknown
  emails to close user enumeration.

## [0.2.0] — 2026-07-29

The declarative metric layer.

### Added
- **Metric registry.** One YAML definition per metric generates the SQL, the argument
  validation, the tool schema the model sees, and the RBAC scope. Adding a metric is
  adding a file.
- **Eval harness**: 26 golden questions across direct, indirect, granularity,
  multi-tool, grounding, RBAC and adversarial categories, with three mechanical graders.
  Dataset integrity and the fixture's expected values are verified without an API key.
- `docs/architecture/metric-registry.md`.

### Changed
- `get_churn_rate` became `get_metric_value`, which reads any snapshot-capable metric.
- **MRR is measured as of period end**, the standard convention for a stock measure. A
  subscription cancelling on 15 March counts towards February's closing MRR, not March's.
- `app/validator/query_validator.py` shrank from 495 to 182 lines, keeping only what is
  not a metric reading.
- `seed.py` is reproducible (`--seed`, default 20260101). It was unseeded, so the demo
  database differed on every run and nothing could be asserted about it.

### Fixed
- **Three separate definitions of MRR** existed in one module: a point-in-time sum for
  trends and two `status == 'active'` variants for segment comparison and customer
  ranking. "MRR trend" and "compare MRR by segment" returned numbers that could not be
  reconciled.
- `arr` returned the `mrr` series unchanged; it is now derived as 12 × MRR.
- `granularity` was declared, advertised to the model, validated, and then ignored by
  every handler.

## [0.1.0] — 2026-07-29

Stop-the-bleeding pass.

### Fixed
- **Empty `JWT_SECRET` produced forgeable tokens.** The default was `""` and the app
  booted happily; `python-jose` both signs and verifies with an empty key, so any visitor
  to a default deployment could mint an admin token for any tenant. Configuration now
  fails fast.
- **The refresh token was an access token** — minted by the same function with identical
  claims, making the httpOnly cookie a seven-day bearer credential.
- **Parallel tool calls were broken.** Tool state was tracked in scalars, so a message
  with two `tool_use` blocks kept only the last and replied with one `tool_result`, which
  the API rejects as malformed.
- **The agent loop was unbounded** — `while True` with no step, token or time ceiling.
- SQLite-only `strftime` replaced with a Python period spine, so trends work on the
  PostgreSQL the deployment guide recommends.
- Synchronous SQLAlchemy inside the async streaming generator now runs in a threadpool
  instead of blocking the event loop for every concurrent request.
- **Removed fabricated data presented as live telemetry**: a hardcoded `$48,250` MRR
  sidebar under a pulsing "Active DB Connected" badge, and a hardcoded "Admin User"
  regardless of who signed in.

[Unreleased]: https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/releases/tag/v0.3.0
[0.2.0]: https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/releases/tag/v0.2.0
[0.1.0]: https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/releases/tag/v0.1.0
