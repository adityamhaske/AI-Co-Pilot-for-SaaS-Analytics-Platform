# Deployment — free-tier guide

This deploys the whole stack without paying for hosting; the only paid line item is Anthropic API usage (and that's the point of the project).

## 1. Database — Neon or Supabase (Postgres, free tier)

1. Create a free project on Neon (neon.tech) or Supabase (supabase.com).
2. Copy the connection string into `DATABASE_URL`.
3. Run `alembic upgrade head` against it, then `python -m app.db.seed` once to populate synthetic demo data.

(Local dev can keep using SQLite — only the deployed environment needs Postgres.)

## 2. Backend — Render or Fly.io (free tier)

**Render**
1. New "Web Service" → connect the GitHub repo → root directory `backend/`.
2. Build command: `pip install -r requirements.txt`. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Add environment variables: `ANTHROPIC_API_KEY`, `JWT_SECRET`, `DATABASE_URL`, `CORS_ORIGINS` (your Vercel frontend URL).
4. Free tier services sleep after inactivity — note the cold-start latency this introduces and mention it if you're benchmarking the p95 latency claim publicly (benchmark against a warm instance, and disclose cold-start behavior separately).

**Fly.io** is a good alternative if you want the service to stay warm longer on the free allowance — `fly launch` from `backend/`, set secrets with `fly secrets set`.

## 3. Frontend — Vercel (free tier)

1. Import the repo, set root directory to `frontend/`.
2. Framework preset: Vite.
3. Environment variable: `VITE_API_BASE_URL` pointing at the deployed backend URL.
4. Vercel handles HTTPS and CDN automatically on the free tier.

## 4. CORS

Set `CORS_ORIGINS` on the backend to the exact Vercel URL (and `http://localhost:5173` for local dev). Don't use `*` once JWT auth is in play.

## 5. CI/CD — GitHub Actions (free for public repos)

Suggested workflow: on push to `main`, run backend tests + lint, frontend tests + lint, and (optionally) trigger Render/Vercel deploy hooks. Keep secrets (`ANTHROPIC_API_KEY` etc.) in GitHub Actions secrets, never in the workflow file.

## 6. Cost control for the Anthropic API

- Use Claude Haiku for the optional injection-classification side-call (cheap, fast) and a stronger model only for the user-facing answer if budget allows — or use one model consistently if you'd rather keep it simple.
- Cap `max_tokens` on responses; the analytics answers don't need long completions.
- Add the row/range caps from `SECURITY.md` so a single query can't balloon token usage by stuffing huge tool results into context.
- Set a low rate limit (see `API_REFERENCE.md`) so a demo link shared publicly can't run up a large bill.

## 7. Smoke test after deploying

1. Log in, confirm JWT issued.
2. Ask a basic metric question, confirm SSE stream renders token by token.
3. Try a question that requires a tool restricted to `analyst`/`admin` while logged in as `viewer`, confirm a clean rejection.
4. Run the latency benchmark script (see `PROMPT_FOR_ANTIGRAVITY.md` §8) against the deployed URL and record the result in your portfolio writeup — note whether you benchmarked a cold or warm instance.
