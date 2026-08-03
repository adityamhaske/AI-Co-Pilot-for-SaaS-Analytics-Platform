# AI co-pilot for SaaS analytics

[![CI](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/actions)
[![Security](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/actions/workflows/security.yml/badge.svg)](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/actions/workflows/security.yml)

Ask questions about SaaS metrics in plain English. Get a streamed, chart-backed answer
where **the model never writes SQL and never decides what a metric means** — and every
figure shows the query behind it.

![The co-pilot answering a multi-tool question about an MRR drop](docs/images/02-analysis.png)

One question, two tool calls, and an answer that names the numbers it used. The
`get_metric_trend` line underneath is the actual call, with its actual arguments.

## What makes it different from a chat box over a database

**Metrics are declared, not written.** One YAML file per metric in
[`backend/app/metrics/definitions/`](backend/app/metrics/definitions) generates the SQL,
the argument validation, the tool schema the model sees, and the RBAC scope. The model
picks *which* registered metric and *which* arguments; it cannot invent a formula.

```yaml
name: mrr
label: Monthly Recurring Revenue
short_label: MRR
description: >
  Total monthly recurring revenue from subscriptions active as of the end of the period.
kind: point_in_time_sum
minimum_role: viewer
supports: [trend, snapshot, compare]
source:
  model: subscription
  value_column: mrr
  interval_start: start_date
  interval_end: end_date
```

That is the whole definition. `arr` is one more file saying *derived from mrr, factor 12*,
so the two can never drift. This replaced a module that contained **three different
definitions of MRR** — "MRR trend" and "compare MRR by segment" returned numbers that
could not be reconciled.

**It declines instead of guessing.** The system prompt permits only figures a tool
returned. Asked for something no tool can answer, it says so:

![The co-pilot refusing to forecast](docs/images/04-grounding.png)

**A ratio shows its terms.** "16.7%" is not checkable. "2 of 12" is.

![Churn rate with its numerator and denominator](docs/images/05-provenance.png)

**Follow-ups resolve against context.** "Who were those two accounts?" only means
something because the previous turn is in the conversation.

![A follow-up question resolving against the previous turn](docs/images/03-followup.png)

## Security boundary around the agent loop

Every tool call is authorised **twice** — at exposure (the model is only shown the tools,
and the metrics inside them, that the caller's role permits) and again at execution. Every
query is scoped to the tenant in the verified JWT, never to anything the model produced.

```
Browser ──► POST /api/copilot/query  (Bearer access token, typ=access)
              │
              ├─ auth        verify signature, expiry, token type → {user, tenant, role}
              ├─ guardrails  input screening; per-user daily cost ceiling
              ├─ agent loop  bounded three ways: step count, wall clock, per-request
              │     │
              │     ├─► provider (Anthropic | OpenAI | Gemini), streaming
              │     │      tools = only those this role permits
              │     │
              │     └─◄ one or more tool calls
              │            ├─ re-check RBAC per call
              │            ├─ validate arguments with Pydantic
              │            ├─ compile the metric definition to tenant-scoped SQL
              │            └─ return rows as data, never as instructions
              │
              └─► SSE: {type: token | tool_call | tool_result | usage | error}, [DONE]
```

Read [SECURITY.md](SECURITY.md) for what this does **not** cover — the prompt-injection
guard is telemetry, not a control, and it says so.

## Choose your model provider

Set two environment variables. Only the selected provider's SDK and key are needed.

```bash
LLM_PROVIDER=anthropic     # or openai, or gemini
ANTHROPIC_API_KEY=sk-...   # or OPENAI_API_KEY / GEMINI_API_KEY
LLM_MODEL=                 # blank uses the provider's default
```

| Provider | Default model | Install |
|---|---|---|
| `anthropic` | `claude-sonnet-4-6` | `pip install anthropic` |
| `openai` | `gpt-4.1` | `pip install openai` |
| `gemini` | `gemini-flash-latest` | `pip install google-genai` |

The agent loop is provider-neutral: it speaks the types in
[`app/providers/base.py`](backend/app/providers/base.py) and never touches a vendor SDK.
Each adapter translates tool schemas, conversation shape and streaming events — the three
things every vendor does differently — in both directions, and both are tested directly:
[outbound](backend/tests/test_providers.py) (neutral types to each wire format) and
[inbound](backend/tests/test_provider_streams.py) (each SDK's response objects back to
neutral types). The split matters: the outbound half was well covered and none of it was
wrong, while **every** bug the first live run found was inbound — an enum that stringified
to `FinishReason.STOP`, an opaque token that had to round-trip, arguments arriving as
fragments keyed only by an index. Spend is priced per provider, so
switching does not silently meter against the wrong rates.

## Dark theme

Both themes are separately chosen sets of steps, not a lightness flip. Chart colours are
validated for colour-vision separation and contrast against each surface.

![The empty state in dark theme](docs/images/06-dark.png)

## Status — read this first

This is a **working demonstration, not a product.**

- **The data is synthetic**, generated by `backend/app/db/seed.py`. There is no connector
  and no import path for real metrics.
- **There is no signup.** Accounts exist only because the seed script creates them.
- **It has not been run in production**, and the metric definitions have not been checked
  against a real accounting of revenue.
- **The accuracy figure below is one provider, one run, 26 questions.** It is a smoke
  test of tool selection, not a benchmark, and the sample is far too small to publish a
  confidence interval for.

[OVERHAUL_PLAN.md](OVERHAUL_PLAN.md) is a candid engineering review of what was broken and
what it would take to make this real.

## Getting started

**Prerequisites:** Node.js 20+, Python 3.11+, and an API key for one provider.

### Docker

Production-shaped: Postgres, migrations as a one-shot service, the API under gunicorn, the
frontend built and served by nginx.

```bash
cp backend/.env.example backend/.env   # set LLM_PROVIDER and the matching API key
export LLM_PROVIDER=gemini             # or anthropic (default), or openai
docker compose up --build
```

`LLM_PROVIDER` is needed **twice, in two different places**, and they are not
interchangeable. In `backend/.env` it selects the provider at run time; exported in the
shell it is a build argument that decides which vendor SDK is installed into the image.
Only one client is baked in, which is the point of the extras — but it means switching
provider is `docker compose up --build`, not a restart. Miss the export and the image
starts cleanly and then fails on the first question with
`The 'google-genai' package is not installed`.

Open <http://localhost:8080>. Sign in as `admin@test.com` / `password123`.

Seeded roles are `admin@test.com`, `analyst@test.com` and `viewer@test.com` — worth trying
more than one, since the available tools and metrics change with the role.

### Manual

```bash
# Backend — http://localhost:6001
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # set LLM_PROVIDER, its API key, and JWT_SECRET
alembic upgrade head
python -m app.db.seed   # reproducible synthetic multi-tenant data
uvicorn app.main:app --reload --port 6001
```

```bash
# Frontend — http://localhost:6002
cd frontend
npm install
npm run dev
```

`JWT_SECRET` must be at least 32 characters; the app refuses to start otherwise and
rejects known placeholders. Generate one with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

## Tests and evals

```bash
cd backend && ENVIRONMENT=test PYTHONPATH=. pytest
```

312 backend tests plus 47 frontend tests, no API key needed. Metric arithmetic is
deterministic and asserted to exact numbers; provider translation, tenant isolation,
token revocation and the agent loop's bounds are all covered. The suite passes
identically under all three `LLM_PROVIDER` values, so a local `.env` cannot change the
result.

```bash
cd frontend && npm test
```

The same backend suite also runs against PostgreSQL in CI, where seven additional
row-level-security tests become active — SQLite has no RLS, so they skip locally:

```bash
cd backend && DATABASE_URL=postgresql+psycopg://user:pass@localhost/db \
  ENVIRONMENT=test PYTHONPATH=. pytest
```

What is *not* deterministic is whether the model picks the right tool with the right
arguments. That is measured separately against 26 golden questions — direct and indirect
phrasing, granularity, multi-tool requests, out-of-scope questions it should decline, RBAC
probes, and prompt-injection attempts:

```bash
cd backend && ANTHROPIC_API_KEY=sk-... PYTHONPATH=. python -m evals.runner
```

Most recent run — `gemini-flash-latest`, 2026-07-30, 26/26, median latency 4.5s:

| Category | | Category | |
|---|---|---|---|
| direct | 8/8 | indirect | 4/4 |
| multi_tool | 2/2 | granularity | 2/2 |
| grounding | 3/3 | rbac | 4/4 |
| adversarial | 3/3 | | |

Read that number narrowly. It is **one provider on one run against 26 questions**, on
synthetic data whose expected values are hand-computed in
[`evals/fixtures.py`](backend/evals/fixtures.py) — it says the tool layer and the refusal
behaviour hold up on the cases we thought to write, and nothing about questions nobody
tried. The first honest run scored **92.3%**; the two failures were graders that banned a
substring appearing in a *correct* refusal, and the assertions now test for disclosure
rather than for a word.

An earlier run reported a perfect score while eight cases had produced no answer at all —
the model called the right tool, then spent its whole step budget and emitted an error,
which the tool grader counted as a pass. Every case is now graded for completion first. The
cause was that the model had no idea what today's date was and was guessing years; see
[`orchestrator/prompts.py`](backend/app/orchestrator/prompts.py).

This calls a real API and costs money, so it runs nightly rather than per commit. The
harness itself — dataset integrity and the fixture's hand-computed expected values — is
verified on every commit without a key. See [backend/evals/README.md](backend/evals/README.md).

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 19 + Vite + TypeScript, Tailwind with semantic tokens, Recharts |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic |
| LLM | Anthropic, OpenAI or Gemini — selected by config |
| Streaming | Server-Sent Events over `StreamingResponse` |
| Auth | JWT with typed access/refresh tokens, rotation and revocation; bcrypt |
| Database | SQLite locally, PostgreSQL for deployment |
| Limits | slowapi, plus a per-user daily cost ceiling metered from token usage |
| Serving | gunicorn + uvicorn workers; nginx for the static bundle |
| CI | GitHub Actions — lint, typecheck, tests, dependency and secret scanning, nightly evals |

## Documentation

| File | What's in it |
|---|---|
| [OVERHAUL_PLAN.md](OVERHAUL_PLAN.md) | Engineering review: what was broken, what a product would need |
| [docs/architecture/metric-registry.md](docs/architecture/metric-registry.md) | The metric definition format, and why metrics are declared |
| [docs/architecture/overview.md](docs/architecture/overview.md) | System design and request lifecycle |
| [docs/reference/api.md](docs/reference/api.md) | Endpoints, the SSE event contract, tool schemas |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability, and known limitations |
| [docs/security/design.md](docs/security/design.md) | Token design, RBAC matrix, injection defences and their limits |
| [backend/evals/README.md](backend/evals/README.md) | What the evals measure and how to add a case |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Local development and what review asks about |
| [CHANGELOG.md](CHANGELOG.md) | What changed and why |

## License

MIT
