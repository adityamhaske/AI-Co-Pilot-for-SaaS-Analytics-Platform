# Changelog

Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is below 1.0.0 the API is not stable and minor versions may break it.

## [Unreleased]

### Planned
- Postgres row-level security as a second tenant-isolation layer
- First accuracy figure from a live eval run
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
