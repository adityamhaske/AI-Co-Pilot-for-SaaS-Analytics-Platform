# Contributing

## Setup

```bash
git clone https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform.git
cd AI-Co-Pilot-for-SaaS-Analytics-Platform
```

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ANTHROPIC_API_KEY and JWT_SECRET
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --port 6001
```

Generate a secret with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Sign in with `admin@test.com` / `password123`. Other seeded roles are
`analyst@test.com` and `viewer@test.com`, same password — worth using, since the tool
surface changes with the role.

## Before opening a pull request

```bash
cd backend && ENVIRONMENT=test PYTHONPATH=. pytest && ruff check . && black --check .
cd frontend && npx tsc -b --noEmit && npm run lint && npm run build
```

CI runs exactly these. There is no separate approval path for a red build.

## What review will ask about

**Metric changes.** Add or change a metric by editing YAML in
`backend/app/metrics/definitions/`, not by writing SQL. See
[docs/architecture/metric-registry.md](docs/architecture/metric-registry.md). A metric without a test asserting an
exact number against the fixture in `backend/tests/conftest.py` will be sent back — a
metric nobody has checked is worse than no metric.

**Tenant scoping.** Every query is scoped through `app/metrics/compiler.py`, which always
applies the tenant predicate. A change that constructs a query another way needs to
explain how isolation is preserved, and needs a test in the isolation group.

**Two authorisation gates.** `ROLE_PERMISSIONS` in `app/core/rbac.py` gates the query
shape; `minimum_role` on a definition gates the metric. Widening one must not silently
widen the other.

**Error text.** Exception detail reaches the log, never the model or the client. It can
carry SQL, column names and paths. `ValueError` from argument validation is the exception:
those messages are ours and telling the model why a call was rejected lets it correct
itself.

**No fabricated data in the UI.** No placeholder figures, no example numbers that look
live. If a value is not loaded yet, show a skeleton or say so.

**Design tokens.** Components use `bg-surface` and `text-ink`, never `bg-slate-900`. A
raw Tailwind colour is a bug — it will not respond to the theme. A third chart series
needs the palette re-validated, not a hue that looks nice; see the note in
`frontend/src/index.css`.

## Style

Python is formatted with `black` and linted by `ruff` (`E,W,F,I,B,UP,C4,S,RUF`).
TypeScript is checked with `tsc --noEmit` and ESLint.

Comments should explain *why*, especially where the code looks odd. Several fixes in this
repository are non-obvious — measuring `scrollHeight` at zero height, reading tool blocks
off the assembled message rather than the deltas — and a comment is what stops them being
"simplified" back into bugs.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. Say what broke and why the
change fixes it, not just what you touched.

## Evals

Model behaviour is measured separately from the deterministic tests:

```bash
cd backend && ANTHROPIC_API_KEY=sk-... PYTHONPATH=. python -m evals.runner
```

This costs real money, so it runs nightly rather than per commit. If you change a tool
description, run at least `--category direct` — the description is the only thing the
model has to distinguish `mrr` from `arr`.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
