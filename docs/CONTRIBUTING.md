# Contributing / development guide

This is a solo portfolio project, but it's written as if a team will read the code — that consistency is part of what it's demonstrating.

## Local development workflow

1. Branch naming: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`, `chore/<short-name>`.
2. Commit messages follow Conventional Commits: `feat(orchestrator): add compare_segments tool`, `fix(auth): reject tokens missing tenant_id`.
3. Every PR (even to yourself) should pass: `pytest` (backend), `npm test` (frontend), `ruff check` / `black --check` (backend lint), `eslint` (frontend lint).
4. Update the relevant `.md` file in the same PR as the code change — `ARCHITECTURE.md` for structural changes, `SECURITY.md` for anything touching auth/RBAC/validation, `API_REFERENCE.md` for endpoint or tool schema changes. Docs drifting from code is treated as a bug.

## Coding standards

### Backend (Python)
- Formatting: `black`. Linting: `ruff`.
- Type hints everywhere; `mypy` clean (or at minimum no untyped function signatures in `app/`).
- No raw SQL string interpolation, ever — see `SECURITY.md` §4. This is enforced by code review, and ideally by a `ruff` rule or custom CI grep for `f"SELECT` / `.format(` near query code.
- New analytics capability checklist (adding a tool):
  1. Add the JSON schema to `app/orchestrator/tools.py` and to `API_REFERENCE.md`.
  2. Add the Pydantic argument model and handler to `app/validator/query_validator.py`.
  3. Add a row to the RBAC matrix in `SECURITY.md` and the enforcement code in `app/core/rbac.py`.
  4. Add positive and negative tests (allowed role succeeds, disallowed role rejected, tenant scoping enforced).

### Frontend (TypeScript/React)
- Formatting: Prettier. Linting: ESLint with the React + TypeScript recommended configs.
- Components are function components with explicit prop types; no implicit `any`.
- All API calls go through `src/lib/api.ts`; no inline `fetch` calls scattered across components.
- Theme tokens (see below) live in `src/theme/`; components reference tokens, not hardcoded hex values.

## Light theme — design constraints

The product ships light-themed only for v1.

- Background: near-white, not pure `#FFFFFF` (use a very light neutral, e.g. `#FAFAF8`, to avoid a stark/clinical feel).
- Text: dark neutral (e.g. `#1F2328`), not pure black.
- One accent color used consistently for primary actions and active states; avoid rainbow UI.
- Charts use a small, consistent color palette (3–5 colors) reused across all chart types — don't let each chart invent its own palette.
- Maintain WCAG AA contrast (4.5:1 for body text) — check this for chart labels and muted/secondary text especially, since those are the easiest to get wrong.
- No dark-mode toggle in v1; don't build the infrastructure for it unless asked, to keep scope tight.

## Running things locally

See `README.md` "Getting started" for the canonical setup steps — don't duplicate them here; if you find yourself updating setup steps, update them in `README.md` and link to it.

## Adding a new database-backed metric

1. Add/extend the model in `app/db/models.py`.
2. Add an Alembic migration: `alembic revision --autogenerate -m "add <thing>"`, review the generated migration by hand before applying.
3. Extend `app/db/seed.py` so the Faker-generated synthetic dataset includes realistic values for the new field.
4. Follow the "new analytics capability checklist" above if it should be queryable by the co-pilot.
