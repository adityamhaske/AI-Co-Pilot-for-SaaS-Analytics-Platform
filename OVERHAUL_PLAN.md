# Overhaul Plan — from demo to launchable

**Author:** Principal-engineer review, 2026-07-28
**Scope:** full end-to-end evaluation, target architecture, repository restructure, and roadmap to public launch.
**Method:** every claim below was checked against the code. Empirically verified items are marked ✅.

---

## Part A — Verdict

### What this actually is

A working, coherent, ~2,800-LOC demonstration of a real pattern: *LLM tool-use as a
typed, permission-gated interface to a database, streamed over SSE.* The pattern is
correct and, honestly, more interesting than most "chat with your data" projects,
because it grounds the model in **hand-written tool handlers** rather than letting it
write SQL. That's the same instinct every serious vendor has (semantic layer over
text-to-SQL), arrived at independently.

The repo is clean. No secrets committed, no vendored junk, 76 tracked files,
sensible `.gitignore`, green CI, conventional commits, real Alembic migration.
That is genuinely better hygiene than most portfolio projects.

### Two grades

| Lens | Grade | Why |
|---|---|---|
| **Portfolio project** | **B+** | Coherent architecture, real streaming, real RBAC, real tests, real CI. Reads as competent. Held back by hardcoded fake data in the UI and docs that overclaim. |
| **Production-ready public product** | **D−** | Cannot be launched. No signup, no way to load your own data, forgeable auth under default config, wrong analytics, a streaming loop that breaks on parallel tool calls, and untested business logic. |

### Can it be launched today?

**No.** Not "needs polish" — three independent blockers, any one of which is fatal:

1. **Nobody can use it.** There is no signup. Users exist only via `backend/app/db/seed.py`.
   A public visitor has no account and no way to get one.
2. **There is no data.** Every number comes from `Faker`-seeded synthetic companies.
   There is no connector, no import, no way to point it at real metrics.
3. **The numbers are wrong.** See Part B, items 5–7. An analytics product that
   returns confidently-worded wrong numbers is worse than no product.

### The uncomfortable part

`README.md` opens with *"a from-scratch, working implementation of the pattern described
as:"* followed by a **resume bullet quoted verbatim**, then: *"Every clause in that
sentence corresponds to a real, tested component in this repo."*
`docs/PROMPT_FOR_ANTIGRAVITY.md` is the AI build brief used to generate the codebase,
left in the repo.

For a portfolio repo, that framing is merely unusual. For a **public launch**, it tells
every visitor that the artifact exists to substantiate a claim rather than to solve a
problem. It has to go — not because it's dishonest, but because it inverts the pitch.

And the sidebar in `frontend/src/components/chat/Chat.tsx:224–244` displays
`$48,250` MRR, `2.1%` churn, `$120` ARPU, `1,240` customers — **hardcoded string
literals** — directly beneath a pulsing green *"Active DB Connected"* badge
(`Chat.tsx:215`). The profile footer reads *"Admin User"* / *"AD"* regardless of who
logged in (`Chat.tsx:280–284`). That is fabricated data presented as live telemetry.
On a public launch it is the single most damaging thing in the repo, and it is also
the easiest to fix.

---

## Part B — The ten things that must be fixed before anyone sees this

Ordered by severity. Everything here was verified against the code.

### 1. Empty `JWT_SECRET` silently produces forgeable tokens ✅ CRITICAL

`backend/app/core/config.py:7` — `jwt_secret: str = ""`. The app boots happily with it.
Empirically verified with the installed `python-jose 3.5.0`:

```
encode with empty key OK -> eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
decode  with empty key -> {'sub': 'attacker', 'tenant_id': 'tenant_test', 'role': 'admin'}
```

Anyone who deploys without setting `JWT_SECRET` — the default path — grants every
visitor the ability to mint an `admin` token for any tenant. There is no startup check.

**Fix:** `jwt_secret: SecretStr` with no default and a `min_length=32` validator; fail
fast at import. Add a startup assertion that refuses to boot in non-debug mode with a
weak secret. Rotate to asymmetric (RS256/EdDSA) once there is more than one service.

### 2. The refresh token *is* an access token — CRITICAL

`backend/app/api/auth.py:42–47` mints the refresh token by calling
`create_access_token()` with identical claims and a 7-day expiry. There is no `typ`
claim, no `jti`, no rotation, no revocation list.

Consequences, all real:
- The refresh cookie is a **7-day valid access token**. Steal the cookie, call the API directly.
- An access token can be replayed at `/auth/refresh`, and vice versa.
- `/auth/refresh` (`auth.py:63–89`) **never touches the database**. Demote a user from
  admin to viewer, or delete them entirely, and their token keeps minting fresh admin
  access tokens for seven days.

**Fix:** distinct `typ: "access" | "refresh"` claims, verified on use. `jti` + a
`refresh_tokens` table for rotation and revocation. Re-read user/role/tenant from the DB
on every refresh. Add `/auth/logout` that revokes.

### 3. The agent loop breaks on parallel tool calls — CRITICAL

`backend/app/streaming/sse.py:17–20` tracks `current_tool_id`, `current_tool_name`,
`current_tool_input` as **scalars**, and never reads `event.index`.

Claude routinely emits multiple `tool_use` blocks in one message ("compare MRR and churn"
is enough to trigger it). When it does:
- The scalars hold only the **last** block; earlier ones are silently dropped.
- `input_json_delta` fragments from interleaved blocks concatenate into one corrupt
  JSON string, so `json.loads` at `sse.py:56` either throws or produces garbage arguments.
- `sse.py:77–88` appends **one** `tool_result` for an assistant message containing **N**
  `tool_use` blocks. The Anthropic API requires a matching `tool_result` for every
  `tool_use` block — the next request in the loop is rejected as malformed.

**Fix:** accumulate blocks in a `dict` keyed by `event.index`; execute all of them
(concurrently); append a `tool_result` per `tool_use_id` in a single user message.

### 4. Unbounded agent loop = economic denial of service — HIGH

`sse.py:16` is `while True:` with no iteration cap, no token budget, no wall-clock
timeout, no cost accounting. Rate limiting (`backend/app/core/limiter.py:3`) is keyed by
`get_remote_address` — **IP, not user** — so behind any load balancer or corporate NAT
all users share one bucket, and `10/minute` is per-*request*, not per-*token*.
`/auth/login` has no limit at all (only `/copilot/query` carries the decorator), so
credential stuffing is unmetered.

**Fix:** `MAX_AGENT_STEPS` (6 is generous), a per-request token ceiling, a wall-clock
timeout, per-user/tenant rate limits keyed on `sub`, and a daily spend cap enforced in
the DB. Rate-limit `/auth/login` by IP *and* by email.

### 5. `arr` and `mrr` return identical numbers, and neither is MRR — HIGH

`backend/app/validator/query_validator.py:60–77`:

```python
if metric in ("mrr", "arr"):
    ... func.sum(Subscription.mrr) ... .group_by(strftime("%Y-%m", Subscription.start_date))
```

Two defects:
- **ARR is never multiplied by 12.** `metric="arr"` returns exactly the `mrr` series.
- Grouping by `start_date` computes **new MRR booked in each month**, not MRR. Standard
  MRR is the sum of active subscriptions *as of* each period — a subscription started in
  January contributes to every subsequent month until it cancels. This query counts it once.

A user asking "what's my MRR trend" gets a plausible-looking chart of the wrong quantity.
That is the worst failure mode an analytics product has.

### 6. `granularity` is validated, then ignored — HIGH

`query_validator.py:18` declares `granularity: Literal["day","week","month"]`, and the
tool schema advertises it to the model (`orchestrator/tools.py:14`). No handler ever
reads it — every branch hardcodes `strftime("%Y-%m", ...)`. Ask for a daily trend, get
monthly buckets labelled as what you asked for.

### 7. The SQL only runs on SQLite — HIGH

`func.strftime` (`query_validator.py:63, 82, 100`) is SQLite-only. `README.md` and
`docs/DEPLOYMENT.md` both recommend PostgreSQL (Neon/Supabase). On Postgres,
`get_metric_trend` raises `UndefinedFunction` for all three metrics — i.e. the flagship
tool fails on the recommended production database. `DATABASE_URL` also defaults to
`sqlite:///./test.db` (`config.py:8`), so a misconfigured deploy silently writes to an
ephemeral file.

**Fix:** `sqlalchemy.func.date_trunc` via a dialect-neutral helper, and CI running
against a real Postgres service.

### 8. Synchronous DB queries inside an async streaming generator — HIGH

`stream_orchestrator` is an `async def` generator, but `execute_tool` (`sse.py:63`) runs
**blocking** SQLAlchemy against a sync `Session`. Every tool call stalls the entire event
loop — not just that request. With `10/minute` per IP and multi-second Anthropic calls,
a handful of concurrent users is enough to serialize the whole server.

There is a second, sharper question here I could not settle without running it: whether
the `Depends(get_db)` yield-dependency's session is still open while the
`StreamingResponse` body iterates on FastAPI 0.138 / Starlette 1.3. If it is torn down
first, every tool call in production is a use-after-close. **This needs an empirical
test before anything else ships** — it is the one item in this list I have not verified.

**Fix:** async SQLAlchemy (`AsyncSession` + `asyncpg`), and own the session's lifetime
explicitly inside the generator rather than inheriting it from the request scope.

### 9. The injection guard is five regexes — HIGH

`backend/app/guard/injection_guard.py:6–12`. It blocks literal `"ignore prior
instructions"`, `"you are now a"`, `"forget what I told you"`, `"system prompt"`,
`"print your instructions"`. Trivial bypasses: *"disregard the above"*, *"nevermind
earlier directions"*, base64, translation, *"repeat everything before this sentence"*,
Unicode homoglyphs, whitespace injection between letters.

More importantly it only guards the **input**. Tool results are serialized straight into
the model's context at `sse.py:66` with no sanitization, so any attacker-controlled
string that reaches the database — a customer name, an `event_type` — is an **indirect
injection** vector. And there is no output-side guard at all.

**Fix:** treat the regex list as telemetry, not a control. The real controls are the ones
already half-present: RBAC-scoped tool exposure (keep it, tighten it), structural
separation of tool results from instructions, and never letting the model's output
authorize anything.

### 10. The module that computes every number is 26% covered ✅ HIGH

Measured, just now:

```
app/validator/query_validator.py     141    105    26%   ← all the business SQL
app/streaming/sse.py                  42     16    62%   ← the agent loop
TOTAL                                424    133    69%
```

20/20 tests pass in 0.98s. But that 26% is imports and Pydantic class bodies — **not one
line of the SQL that produces the answers is executed by a test.** Nor is tenant
isolation, the single most important security property in a multi-tenant system, tested
anywhere. `test_rbac.py` builds its own throwaway `FastAPI()` app rather than testing the
real one, so it validates the helper, not the deployed behavior.

### Also confirmed, below the top ten

| Issue | Location | Note |
|---|---|---|
| Invalid Tailwind class ✅ | `Chat.tsx:362, 385` | `bg-slate-850` / `border-slate-850` — not in the default palette, not in `tailwind.config.js`. Renders as nothing. |
| README claims SSE "via `sse-starlette`" ✅ | `README.md` | `sse-starlette` is in `requirements.txt` but **imported nowhere**. SSE is hand-rolled `f"data: ..."` strings. |
| README claims auth "via `python-jose`/PyJWT" ✅ | `README.md` | It's `python-jose` only. PyJWT isn't a dependency. |
| Port incoherence ✅ | `docker-compose.yml:21` vs `vite.config.ts:9` | Compose maps `5173:5173`; Vite serves on `6002`; CORS allows `6002`; README says open `5173`. The documented Docker quickstart cannot work. |
| React state mutation | `Chat.tsx:136–143` | Mutates message objects in place inside `setMessages`. Unsafe under StrictMode/concurrent rendering. |
| SSE `[DONE]` breaks the wrong loop | `Chat.tsx:128` | `break` exits the inner `for`, not the outer `while` — terminates only because the stream closes. |
| Sentinel-as-control-flow | `Chat.tsx:139` | Uses the literal string `"_Calling"` inside message content to decide append-vs-replace. |
| No `AbortController` | `Chat.tsx:97` | Navigate away mid-stream and the backend keeps generating and billing. |
| Token in React state only | `App.tsx:6` | Page refresh = forced re-login. The 14-min refresh timer only starts post-login. |
| Dev servers in both Dockerfiles | `backend/Dockerfile:10`, `frontend/Dockerfile:10` | `uvicorn --reload` and `vite dev`. Not production images. No multi-stage, no non-root user, no healthcheck, no `.dockerignore`. |
| Ruff configured with zero rules ✅ | `pyproject.toml:33` | Only `line-length` and `target-version`. No `select`, so it runs a near-empty default ruleset. |
| `structlog` never configured | `guard/injection_guard.py:4` | Imported in exactly one module; no processors, no renderer, no request ID. Auth failures and tool executions are unlogged. |
| `datetime.utcnow()` deprecated | `core/security.py:28,30`, `db/models.py:12` | Removed path in 3.12+. |
| `RoleChecker(allowed_endpoints=...)` is dead | `core/rbac.py:62` | Parameter accepted, never used; the check reads the global matrix. `path.startswith(ep)` also matches `/api/copilot/queryXYZ`. |
| Duplicate READMEs | `README.md` vs `docs/README.md` | Near-identical, already drifting (`docs/README.md` documents `npm test`, which doesn't exist in `package.json`). |
| Missing `Customer.tenant_id` filter | `query_validator.py:361–368` | `list_active_alerts` joins Customer↔UsageEvent filtering only `UsageEvent.tenant_id`. Currently safe by ID uniqueness; a defense-in-depth gap. |
| `no_data` sentinel | `query_validator.py:119` | `[{"date":"no_data","value":0}]` flows into both the chart and the model's context as if it were data. |
| Unrealistic seed data | `db/seed.py:75` | 50/50 active/canceled coin flip, `invoice.amount == sub.mrr` always, no time correlation. Produces ~50% churn — visibly fake. |

---

## Part C — Strategy

### The real problem isn't the bug list

Every defect above is fixable in days. The strategic problem is different:
**this product has no wedge.**

"Chat with your SaaS metrics" is, in 2026, a *feature* that Snowflake (Cortex Analyst),
Databricks (Genie), ThoughtSpot (Spotter), Hex (Magic), Looker (Gemini) and Power BI
(Copilot) all ship inside platforms that already own the customer's data. A standalone
chat box competing with them, with no connectors and no distribution, loses on every axis.

So the question is not "how do I make this better." It's **"what is this for?"** Three
honest answers:

| | Strategy | Cost | Ceiling |
|---|---|---|---|
| **A** | **OSS reference implementation** — the canonical example of a secure, grounded, multi-tenant AI analytics agent. Launch = GitHub + docs site + hosted synthetic demo. | ~6 weeks part-time | Credibility, stars, inbound. No revenue. |
| **B** | **Real SaaS** — signup, connect your Postgres/Stripe/BigQuery, semantic layer over an unknown schema, billing, quotas. | 6+ months solo | Real revenue, brutal competition, needs distribution you don't have. |
| **C** | **Embeddable AI-analyst SDK** — sell to companies who already have a dashboard: they declare metrics, you supply the agent loop, RBAC tool gating, streaming, guardrails. | 3–4 months + design partners | Good business, sales-led, slow to validate solo. |

### Recommendation: **A, executed to a standard that makes B and C possible later.**

Rationale, plainly:

- **B is not a real plan right now.** Building connectors *and* a semantic layer over
  arbitrary customer schemas *and* billing *and* signup, solo, while Cortex Analyst ships
  free inside the warehouse — that's a way to spend six months and launch nothing.
- **A is launchable in weeks and plays to the code's actual strength.** The genuinely
  valuable idea already in this repo is **RBAC-scoped tool exposure**: the model is only
  *shown* the tools the caller's role permits (`sse.py:13`), and access is re-checked
  before execution (`sse.py:59`). That's a real security pattern for agentic systems and
  almost no open-source example implements it. That's the asset.
- **A is the strictly better career artifact.** A reference implementation that is
  correct, secure, evaluated, and documented beats a half-built SaaS in every reading —
  hiring, consulting, or fundraising.
- **A keeps B and C open.** The metric registry and connector interface below are exactly
  what B needs. Nothing in this plan is wasted if you later commercialize.

But A has a hard condition: **a reference implementation is only worth anything if it's
correct.** Right now it would teach people to do it wrong. So the work is not "polish the
demo" — it is "make it genuinely exemplary."

### What I would explicitly not build

Signup/billing/connectors (that's B — defer until there's demand), a WebSocket transport
(SSE is correct here), a vector store / RAG layer (the tool layer is the grounding
mechanism; RAG would *reduce* correctness), multi-model routing, a mobile app, and any
"AI insights" feature that generates claims not traceable to a tool result.

---

## Part D — Target architecture

### The one idea that changes everything: a declarative metric registry

Today, each metric's definition is **hand-written SQL buried in a 420-line file**
(`query_validator.py`), and the tool schemas that describe those metrics to the model
live in a **separate hand-maintained list** (`orchestrator/tools.py`). Nothing keeps them
in sync — which is precisely how `granularity` became a documented parameter that no
handler reads, and how `arr` became a synonym for `mrr`.

Replace both with a single declarative source:

```yaml
# services/api/src/analyst/metrics/definitions/mrr.yaml
name: mrr
label: Monthly Recurring Revenue
description: Sum of MRR across subscriptions active as of each period.
unit: currency_usd
grain: [day, week, month]
tenant_scoped: true
required_role: viewer
aggregation:
  type: point_in_time_sum        # active AS OF each period — not sum of new bookings
  source: subscriptions
  value_column: mrr
  active_predicate:
    start: start_date
    end: end_date                # null = still active
dimensions: [segment]
derived:
  arr: { from: mrr, multiply: 12 }
```

From one file the system generates: the Anthropic tool schema, the argument-validation
model, the dialect-neutral SQLAlchemy query, the RBAC scope, and the docs entry. The
model can no longer choose the formula; it can only choose *which registered metric* and
*which arguments*. **MRR means exactly one thing, everywhere, forever.**

This is the semantic-layer insight every serious vendor implements and no OSS demo does.
It is the difference between "chatbot over a database" and "trustworthy analytics agent",
and it is the thing worth putting your name on.

### Components

```
Browser ──► POST /api/v1/chat  (JWT access token, 15 min)
              │
              ├─ auth        verify typ=access, sig, exp → {user, tenant, role}
              ├─ guardrails  input screening (telemetry), budget check
              ├─ agent loop  bounded: MAX_STEPS, token ceiling, wall-clock timeout
              │     │
              │     ├─► Anthropic Messages API (streaming, prompt-cached system+tools)
              │     │      tools = registry.tools_for_role(role)   ← RBAC-scoped exposure
              │     │
              │     └─◄ N parallel tool_use blocks, keyed by content-block index
              │            │
              │            ├─ re-check RBAC per tool (defense in depth)
              │            ├─ compile: definition + args → SQLAlchemy Select
              │            ├─ inject tenant predicate  (+ Postgres RLS as backstop)
              │            ├─ execute on AsyncSession
              │            └─ wrap result as structured data, never as instructions
              │
              └─► SSE: typed events (token | tool_call | tool_result | chart | usage | error | done)
```

### Correctness guarantees, stated as invariants

1. The model never writes SQL. It selects a registered metric and supplies validated arguments.
2. Every metric has exactly one definition, and it is versioned in git.
3. Every generated query carries a tenant predicate, enforced twice: in the compiler, and by Postgres RLS.
4. Every tool is authorized twice: at exposure (the model can't see what the role can't use) and at execution.
5. Every number the user sees is traceable to a tool result. The UI shows the tool, the arguments, and the row count.
6. A golden-question eval suite asserts **exact numeric answers** and gates CI. Accuracy is published in the README.

That last point is the launch asset. "Here is our text-to-analytics accuracy on a public
eval set, run on every commit" is a claim almost nobody makes, and it's the one an
informed reader actually cares about.

---

## Part E — Target repository structure

Monorepo, service-oriented, at the standard you asked for. Phase tags mark what lands when.

```
ai-analyst/                                  # rename — "AI Co-Pilot for SaaS Analytics Platform" is a description, not a name
├── README.md                                # what it is, 60-second quickstart, eval accuracy, architecture diagram
├── LICENSE
├── CHANGELOG.md                             # Keep a Changelog + SemVer
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md                              # vulnerability disclosure policy (NOT design docs)
├── CODEOWNERS
├── Makefile                                 # make dev | test | lint | eval | seed | migrate
├── docker-compose.yml                       # api + web + postgres, coherent ports
├── .dockerignore                            # ← missing today; .venv is in the build context
├── .editorconfig
├── .pre-commit-config.yaml
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                           # lint, typecheck, test+coverage gate, build — with a Postgres service
│   │   ├── eval.yml                         # golden-question accuracy gate
│   │   ├── security.yml                     # pip-audit, npm audit, gitleaks, trivy
│   │   └── release.yml
│   ├── ISSUE_TEMPLATE/{bug.yml,feature.yml}
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml
│
├── docs/
│   ├── README.md                            # index only — never a duplicate of root README
│   ├── architecture/
│   │   ├── overview.md                      # ← from docs/ARCHITECTURE.md, rewritten
│   │   ├── agent-loop.md                    # bounded loop, parallel tools, budgets
│   │   ├── metric-registry.md               # the core idea
│   │   ├── multi-tenancy.md                 # isolation model + RLS
│   │   └── streaming-protocol.md            # typed SSE contract
│   ├── adr/
│   │   ├── 0001-tool-layer-over-text-to-sql.md
│   │   ├── 0002-declarative-metric-registry.md
│   │   ├── 0003-rbac-scoped-tool-exposure.md
│   │   ├── 0004-sse-over-websockets.md
│   │   ├── 0005-postgres-rls-for-tenant-isolation.md
│   │   ├── 0006-access-and-refresh-token-strategy.md
│   │   └── 0007-evals-as-a-ci-gate.md
│   ├── guides/
│   │   ├── quickstart.md
│   │   ├── local-development.md             # ← from docs/CONTRIBUTING.md (dev half)
│   │   ├── adding-a-metric.md               # the contributor's main path
│   │   └── deployment.md                    # ← from docs/DEPLOYMENT.md, rewritten
│   ├── reference/
│   │   ├── api.md                           # ← from docs/API_REFERENCE.md, regenerated from OpenAPI
│   │   ├── sse-events.md
│   │   ├── metric-schema.md
│   │   └── configuration.md                 # every env var, type, default, required?
│   ├── security/
│   │   ├── threat-model.md                  # ← new: STRIDE over the agent loop
│   │   ├── rbac-matrix.md                   # ← from docs/SECURITY.md
│   │   └── prompt-injection.md              # honest about what the guard does and doesn't do
│   └── operations/
│       ├── runbook.md
│       ├── slos.md                          # p95 first-token, availability, eval accuracy floor
│       └── observability.md
│
├── services/api/                            # ← was backend/
│   ├── pyproject.toml                       # single dependency source; DELETE requirements.txt
│   ├── Dockerfile                           # multi-stage, non-root, gunicorn+uvicorn workers, HEALTHCHECK
│   ├── alembic/
│   └── src/analyst/
│       ├── main.py                          # app factory + lifespan
│       ├── config.py                        # ← core/config.py — validated, fail-fast, no unsafe defaults
│       ├── logging.py                        # structlog config + request-id middleware
│       ├── errors.py                         # exception hierarchy; client-safe messages only
│       ├── api/
│       │   ├── deps.py
│       │   └── v1/{router,auth,chat,conversations,health}.py
│       ├── auth/
│       │   ├── tokens.py                    # ← core/security.py — typ, jti, rotation, revocation
│       │   ├── passwords.py
│       │   ├── rbac.py                      # ← core/rbac.py — permissions, not path prefixes
│       │   └── models.py
│       ├── agent/
│       │   ├── loop.py                      # ← streaming/sse.py — THE orchestrator, bounded, index-keyed
│       │   ├── client.py                    # ← orchestrator/orchestrator.py — retry, timeout, prompt caching
│       │   ├── prompts.py
│       │   ├── budget.py                    # step + token + cost ceilings
│       │   └── events.py                    # typed SSE emitter
│       ├── metrics/                         # ← the new core; replaces validator/query_validator.py
│       │   ├── registry.py
│       │   ├── definitions/*.yaml
│       │   ├── compiler.py                  # definition + args → dialect-neutral Select
│       │   ├── tools.py                     # ← orchestrator/tools.py, now GENERATED
│       │   └── execute.py                   # tenant-scoped execution
│       ├── guardrails/
│       │   ├── input.py                     # ← guard/injection_guard.py, demoted to telemetry
│       │   ├── tool_results.py              # indirect-injection containment
│       │   └── policy.py
│       ├── db/
│       │   ├── session.py                   # async engine + AsyncSession
│       │   ├── models/                      # ← db/models.py, split per aggregate
│       │   └── seed/                        # ← db/seed.py, realistic cohort-based generator
│       └── telemetry/{tracing,metrics,costs}.py
│   └── tests/
│       ├── unit/                            # metric compiler, registry, tokens
│       ├── integration/                     # real Postgres, real migrations, real endpoints
│       ├── security/                        # tenant isolation, RBAC, injection, token abuse
│       └── conftest.py                      # function-scoped transactional fixtures
│
├── apps/web/                                # ← was frontend/
│   ├── Dockerfile                           # multi-stage → nginx, not `vite dev`
│   └── src/
│       ├── routes/
│       ├── features/{auth,chat,charts,conversations}/
│       ├── components/ui/
│       ├── lib/{api-client,sse,auth-store,config}.ts   # one apiUrl resolution, not three
│       └── styles/
│   └── tests/{unit,e2e}/
│
├── evals/                                   # ← new: the credibility engine
│   ├── datasets/golden_questions.yaml       # question → expected tool, args, exact numeric answer
│   ├── runner.py
│   ├── graders/{numeric,tool_choice,refusal}.py
│   └── README.md
│
└── packages/shared-types/                   # SSE event contract shared by API and web
```

### Migration table

| Current | Action | Destination |
|---|---|---|
| `backend/app/main.py` | rewrite | `services/api/src/analyst/main.py` (app factory, lifespan) |
| `backend/app/core/config.py` | rewrite | `.../config.py` — no unsafe defaults, fail-fast |
| `backend/app/core/security.py` | rewrite | `.../auth/tokens.py` + `auth/passwords.py` |
| `backend/app/core/rbac.py` | rewrite | `.../auth/rbac.py` — permission-based, drop dead param |
| `backend/app/core/limiter.py` | rewrite | `.../api/deps.py` — key on user, not IP |
| `backend/app/api/auth.py` | rewrite | `.../api/v1/auth.py` — token types, rotation, logout |
| `backend/app/api/copilot.py` | rewrite | `.../api/v1/chat.py` |
| `backend/app/orchestrator/orchestrator.py` | rewrite | `.../agent/client.py` + `agent/prompts.py` |
| `backend/app/orchestrator/tools.py` | **delete** | generated by `metrics/tools.py` |
| `backend/app/streaming/sse.py` | rewrite | `.../agent/loop.py` + `agent/events.py` |
| `backend/app/validator/query_validator.py` | **replace** | `.../metrics/` — declarative registry |
| `backend/app/guard/injection_guard.py` | move + demote | `.../guardrails/input.py` |
| `backend/app/db/models.py` | split | `.../db/models/*.py` + indexes |
| `backend/app/db/session.py` | rewrite | `.../db/session.py` — async |
| `backend/app/db/seed.py` | rewrite | `.../db/seed/` — realistic cohorts |
| `backend/tests/*.py` | rewrite | `tests/{unit,integration,security}/` |
| `backend/tests/benchmark.py` | move + fix | `evals/benchmarks/latency.py` (percentile index off-by-one) |
| `backend/{requirements.txt,pyproject.toml}` | merge | `services/api/pyproject.toml` |
| `frontend/src/App.tsx` | rewrite | `apps/web/src/routes/` + `lib/auth-store.ts` |
| `frontend/src/components/chat/Chat.tsx` | **split** | `features/chat/` — and delete the hardcoded metrics |
| `frontend/src/components/login/Login.tsx` | move | `features/auth/` |
| `frontend/src/components/ui/*` | move | `apps/web/src/components/ui/` |
| `README.md` | **rewrite** | root — remove the resume framing entirely |
| `docs/README.md` | **delete** | duplicate; `docs/README.md` becomes an index |
| `docs/ARCHITECTURE.md` | rewrite | `docs/architecture/overview.md` |
| `docs/API_REFERENCE.md` | rewrite | `docs/reference/api.md` |
| `docs/SECURITY.md` | split | `docs/security/*` + root `SECURITY.md` (disclosure policy) |
| `docs/DEPLOYMENT.md` | rewrite | `docs/guides/deployment.md` |
| `docs/CONTRIBUTING.md` | split | root `CONTRIBUTING.md` + `docs/guides/local-development.md` |
| `docs/PROMPT_FOR_ANTIGRAVITY.md` | **delete** | the AI build brief does not belong in a public repo |
| `frontend/dist/` | **delete** | build artifact; already gitignored but present on disk |
| `backend/{test.db,test_override.db}` | **delete** | ditto |

---

## Part F — Roadmap

| Phase | Name | Exit criteria | Effort |
|---|---|---|---|
| **0** | **Stop the bleeding** | Hardcoded sidebar metrics and "Admin User" gone. `JWT_SECRET` fails fast. Agent loop bounded. `PROMPT_FOR_ANTIGRAVITY.md` deleted, README de-resumed. Docker ports coherent. | 1–2 days |
| **1** | **Correctness core** | Metric registry live; `arr = 12 × mrr`; MRR is point-in-time; `granularity` honored; dialect-neutral SQL; Postgres in CI; parallel tool calls handled; async DB. Coverage of `metrics/` ≥ 90%. | 1.5 weeks |
| **2** | **Trust & safety** | Token `typ`+`jti`+rotation+revocation; DB re-check on refresh; per-user rate limits; token/cost budget; RLS; tenant-isolation tests; structlog + request IDs. Threat model written. | 1 week |
| **3** | **Evals** | ≥60 golden questions; numeric grader; CI gate; accuracy published in README. | 4–5 days |
| **4** | **Product surface** | Conversation persistence + follow-ups; real user identity in the UI; tool-call provenance visible; a11y pass; `AbortController`; token survives refresh. | 1 week |
| **5** | **Launch** | Production Dockerfiles; hosted demo on synthetic data; docs site; `SECURITY.md`; CHANGELOG; v0.1.0 tagged. | 4–5 days |

≈ 6 weeks part-time solo. Phase 0 can start immediately and is worth doing regardless of
which strategy you ultimately pick.

---

## Part G — Next working session

In order, smallest blast radius first:

1. Delete the hardcoded metrics block (`Chat.tsx:220–245`) and the hardcoded profile
   (`Chat.tsx:277–286`). Either wire them to a real `/api/v1/metrics/summary` endpoint or
   remove the panel. Do not ship fabricated numbers under a "DB Connected" badge.
2. Make `config.py` fail fast on a missing/weak `JWT_SECRET` and a SQLite `DATABASE_URL`
   outside dev. One file, ~15 lines, closes the critical auth hole.
3. Bound the agent loop: `MAX_AGENT_STEPS`, token ceiling, wall-clock timeout.
4. Fix parallel tool handling in `sse.py` — dict keyed by `event.index`, one `tool_result`
   per `tool_use_id`. Add the regression test that currently doesn't exist.
5. Settle the `StreamingResponse` + yield-dependency question empirically. It changes the
   shape of the DB refactor, so it should be answered before Phase 1 starts.
6. Rewrite `README.md` without the resume framing; delete `docs/PROMPT_FOR_ANTIGRAVITY.md`
   and `docs/README.md`.
7. Fix `arr`, `granularity`, and `strftime`. Add the first real tests for the SQL.

Items 1–3 and 6 are a single afternoon and move the "public launch" grade from D− to C+
on their own.
