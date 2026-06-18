# Build prompt for Antigravity

Paste everything below this line into Antigravity as the project brief. It assumes the six companion files (`README.md`, `ARCHITECTURE.md`, `API_REFERENCE.md`, `SECURITY.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`) are already sitting in the repo root — point the agent at them rather than having it re-derive the design.

---

## Role

You are an expert full-stack engineer building a production-quality portfolio project: an AI co-pilot for a SaaS analytics dashboard. Treat this as real production code, not a demo — it will be reviewed in technical interviews and the GitHub repo will be linked from a resume.

## Source of truth

Six files already exist in the repo root: `README.md`, `ARCHITECTURE.md`, `API_REFERENCE.md`, `SECURITY.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`. **Read all six before writing any code.** They are the authoritative spec for architecture, API shape, tool schemas, security model, coding standards, and deployment. If you need to make a decision not covered by them, make the most defensible choice and add a short note to the relevant file explaining the decision — do not silently diverge from them, and do not regenerate or rewrite them wholesale.

## What you're building, in one paragraph

A user logs into a SaaS analytics dashboard and asks a question in plain English (e.g. "how did MRR trend over the last two quarters" or "who are our top 10 customers by usage"). The FastAPI backend authenticates the request via JWT, checks the user's role, screens the input for prompt-injection attempts, then hands the conversation to Claude with a fixed set of tool definitions describing the analytics operations available. Claude decides which tool(s) to call; the backend independently validates every tool call against an allow-list, the caller's role, and their tenant before executing a parameterized database query; results go back to Claude; Claude's final natural-language answer streams to the browser token-by-token over SSE, with structured chart data interleaved so the frontend can render a chart alongside the prose.

## Hard constraints — do not violate these

1. **Light theme only.** No dark mode toggle, no dark-mode CSS branch. Background near-white (not pure `#FFFFFF`), text dark neutral (not pure black), one consistent accent color, WCAG AA contrast minimum. See `CONTRIBUTING.md` "Light theme — design constraints" for the exact constraints.
2. **Open source / free tooling only, except the Anthropic API.** Every other dependency — frontend libraries, backend libraries, database, hosting, CI — must be free or open source. If you're about to add a paid SaaS dependency (a paid auth provider, a paid vector DB, a paid monitoring tool), stop and use the open-source or free-tier alternative instead, or implement it directly in code.
3. **The model never executes SQL.** It only ever calls one of the fixed, typed tool functions defined in `API_REFERENCE.md`. There is no general-purpose "run a query" tool.
4. **Tenant scoping comes from the verified JWT, never from tool arguments or model output.** Even if a tool call includes a tenant identifier, ignore it and use the JWT's `tenant_id`.
5. **No raw SQL string interpolation anywhere.** Use SQLAlchemy with bound parameters exclusively.
6. **Secrets only via environment variables.** Ship `.env.example` files with placeholder values; real `.env` files are gitignored from the first commit.
7. **Don't build a phrase-library or test fixture file of literal prompt-injection strings as a "feature" or documentation artifact.** Test the injection guard by category of behavior (see `SECURITY.md` §7), not by maintaining a public list of bypass phrases.

## Tech stack (all open source / free tier except Anthropic)

- Frontend: React + Vite + TypeScript, Tailwind CSS, shadcn/ui, Recharts, TanStack Query, React Router.
- Backend: FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, `sse-starlette`, `slowapi` (rate limiting), `python-jose` or `PyJWT`, `passlib[bcrypt]`.
- LLM: Anthropic Python SDK, Claude with tool use, streaming enabled.
- Database: PostgreSQL for deployed environments (Neon or Supabase free tier), SQLite for local dev — drive the choice from `DATABASE_URL` so both work with the same code.
- Synthetic data: `Faker`, seeded for reproducibility, generating multiple tenants with realistic subscription/invoice/usage data.
- Testing: `pytest` + `httpx` test client (backend), Vitest + React Testing Library (frontend).
- CI: GitHub Actions.
- Hosting (see `DEPLOYMENT.md`): Vercel (frontend), Render or Fly.io (backend), Neon/Supabase (database).

## Build order

Work through these phases in order. Don't jump ahead to the frontend before the backend's auth/RBAC/validation boundary has tests passing — the security model is the point of this project, not an afterthought.

### Phase 0 — scaffolding
- Initialize the folder structure exactly as laid out in `ARCHITECTURE.md` §8.
- Set up `pyproject.toml` (or `requirements.txt`) for the backend and `package.json` for the frontend with the dependencies above.
- Set up `black`, `ruff`, `pytest` config for backend; `eslint`, `prettier`, `vitest` config for frontend.
- Write `.env.example` for both backend and frontend per `SECURITY.md` §5.
- Set up a GitHub Actions workflow that runs lint + tests on push (see `DEPLOYMENT.md` §5).

### Phase 1 — database and synthetic data
- Define SQLAlchemy models for: `tenants`, `users` (with `role`), `customers`, `subscriptions`, `invoices`, `usage_events`. Every business table carries `tenant_id`.
- Write Alembic migrations.
- Write `app/db/seed.py` using `Faker` to generate at least 3 tenants, each with realistic multi-month subscription/invoice/usage history, so MRR/churn/segment queries return interesting, non-trivial results.

### Phase 2 — auth and JWT
- Implement `/api/auth/login` (password check against `passlib` bcrypt hash) and `/api/auth/refresh`, exactly matching the request/response shapes in `API_REFERENCE.md`.
- Implement the JWT issue/verify logic in `app/core/security.py` with the claims structure in `SECURITY.md` §1.
- Write tests: valid login issues a token with correct claims; expired/tampered/missing-claim tokens are all rejected with `401`.

### Phase 3 — RBAC
- Implement `app/core/rbac.py` as a declarative table matching `SECURITY.md` §2, exposed as a FastAPI dependency that can be applied per-endpoint and per-tool.
- Write a full positive/negative test matrix: every role × every tool/endpoint combination in the table gets an explicit test.

### Phase 4 — prompt-injection guard
- Implement `app/guard/injection_guard.py`: a heuristic pre-filter per `SECURITY.md` §3, returning a flag (not a hard block by default — make this configurable) plus a logged event.
- Optionally wire in a cheap Claude Haiku classification call as a second signal, but make sure it's not on the critical path for clearly benign short queries (don't add latency for "what was MRR last month").
- Write category-based tests per `SECURITY.md` §7 — generate test cases programmatically by category (role-redefinition attempts, system-prompt-exfiltration attempts, out-of-scope tool requests) rather than hardcoding a long literal phrase list in the test file.

### Phase 5 — tool-use orchestrator and query validator
- Define the five tool JSON schemas from `API_REFERENCE.md` in `app/orchestrator/tools.py`.
- Implement `app/validator/query_validator.py`: one Pydantic model per tool's arguments, one handler per tool that builds a parameterized SQLAlchemy query scoped by the JWT's `tenant_id`, with row/range caps per `SECURITY.md` §4.
- Implement `app/orchestrator/orchestrator.py`: the loop that sends the user's message + tool schemas to Claude via the streaming Messages API, intercepts `tool_use` blocks, calls the validator, appends `tool_result` blocks, and continues the stream until a final text response completes. Re-check RBAC and tenant scope inside the validator even though the orchestrator already checked it upstream (defense in depth, per `SECURITY.md` §2).
- Write tests: a tool call outside the caller's role is rejected even if "Claude" (mock the Anthropic client in tests) requests it; a tampered tenant_id in tool arguments is ignored in favor of the JWT's.

### Phase 6 — SSE streaming
- Implement `app/streaming/sse.py` converting Anthropic stream events into the SSE event types defined in `API_REFERENCE.md` (`message_start`, `content_block_delta`, `tool_call`, `tool_result`, `chart_data`, `message_stop`, `error`).
- Wire `/api/copilot/query` as a `StreamingResponse` using `sse-starlette`.
- Add `slowapi` rate limiting per `API_REFERENCE.md` §"Rate limiting".

### Phase 7 — frontend
- Build the chat interface: message list, input box, streaming token rendering (consume SSE via `EventSource` or a fetch-based SSE client), a "thinking / calling get_metric_trend..." indicator driven by `tool_call` events.
- Build chart rendering with Recharts, fed by `chart_data` events.
- Build login/auth state, token storage (access token in memory or a short-lived store, refresh token relies on the httpOnly cookie — never put the refresh token in `localStorage`).
- Apply the light theme tokens per `CONTRIBUTING.md` — build a small `src/theme/` module other components reference rather than hardcoding colors.
- Use shadcn/ui components for inputs, buttons, and cards rather than building bespoke versions of common primitives.

### Phase 8 — testing, latency benchmark, and docs sync
- Backend: `pytest` coverage for auth, RBAC, injection guard, query validator, and the orchestrator's tool-call interception (mock the Anthropic client; don't spend real API budget on every CI run).
- Frontend: component tests for the chat stream renderer and chart renderer.
- **Latency benchmark script** (`backend/scripts/benchmark_latency.py`): fire N concurrent requests (suggest N=30) against `/api/copilot/query` against a warm instance, measure time-to-first-SSE-byte per request, report p50/p95/p99. This is what substantiates the "p95 first-token latency under 2 seconds" claim — run it, record the actual numbers, and put them in `README.md` rather than just asserting the target was met.
- Before declaring done, re-read `ARCHITECTURE.md`, `API_REFERENCE.md`, and `SECURITY.md` and update any section where the implementation ended up diverging from the original spec — these documents should describe the code that actually exists, not the code that was originally planned.

## Acceptance criteria

- [ ] A user can log in, ask a natural-language analytics question, and see a streamed answer with an inline chart within ~2 seconds to first token on a warm instance.
- [ ] A `viewer`-role user attempting to trigger an `analyst`-only tool (e.g. by asking a question that would naturally call `compare_segments`) gets a graceful refusal, not an error page or leaked data.
- [ ] Cross-tenant access is impossible even via crafted tool arguments — covered by an explicit test.
- [ ] No SQL string interpolation exists anywhere in the codebase — grep for `f"...SELECT` / `.format(` near query code as a CI check if convenient.
- [ ] All six companion docs accurately describe the final implementation.
- [ ] The app is light-themed, accessible (AA contrast), and free of dark-mode code paths.
- [ ] The full stack runs using only free-tier infrastructure plus the Anthropic API key.

## Tone for any UI copy you write

Plain, confident, no filler ("Here's your analytics co-pilot" rather than "Welcome! We're excited to help you explore your data today!"). Error states should be specific and actionable, not generic ("That question needs analyst access — ask an admin to upgrade your role" rather than "Something went wrong").
