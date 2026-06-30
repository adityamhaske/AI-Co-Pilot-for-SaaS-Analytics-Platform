# AI co-pilot for SaaS analytics platform

[![CI](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/actions)

A natural-language co-pilot for a SaaS analytics dashboard. Ask a question in plain English; the backend maps it to structured, validated calls against analytics data using Claude's tool use, streams the answer back token by token, and renders charts inline — all behind JWT auth, role-based access control, and prompt-injection screening.

Built with React, FastAPI, the Anthropic API, Server-Sent Events, and JWT.

## Why this exists

This project is a from-scratch, working implementation of the pattern described as: *"Built an AI co-pilot enabling natural-language access to a SaaS analytics dashboard via FastAPI and Anthropic function calling, mapping user queries to structured backend calls; implemented SSE token streaming and JWT-authenticated services, achieving p95 first-token latency under 2 seconds; added prompt-injection detection, role-based access control, and query validation at the request boundary."* Every clause in that sentence corresponds to a real, tested component in this repo — see `ARCHITECTURE.md` and `SECURITY.md` for the specifics.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + TypeScript | Fast dev loop, standard for the resume stack |
| Styling | Tailwind CSS + shadcn/ui | Open source, fast to theme (light theme, see below) |
| Charts | Recharts | Open source, React-native |
| Backend | FastAPI | Async-first, plays well with streaming and Pydantic validation |
| LLM | Anthropic API (Claude), tool use | The one paid dependency — this is what the project is demonstrating |
| Streaming | SSE via `sse-starlette` | Simpler and more proxy-friendly than WebSockets for one-directional token streaming |
| Auth | JWT via `python-jose`/`PyJWT` | Stateless, standard |
| Database | PostgreSQL (Neon/Supabase free tier) or SQLite locally | Free-tier friendly, swappable via `DATABASE_URL` |
| Synthetic data | Faker | Generates realistic multi-tenant SaaS metrics without needing real customer data |
| Rate limiting | slowapi | Open source FastAPI rate limiter |
| CI | GitHub Actions | Free for public repos |
| Hosting | Vercel (frontend) + Render or Fly.io (backend) | Free tiers sufficient for a portfolio deployment |

## Architecture

See `ARCHITECTURE.md` for the full system diagram, request lifecycle, and latency budget. Short version: browser → JWT auth → RBAC → prompt-injection guard → tool-use orchestrator → Anthropic API ⇄ query validator → tenant-scoped database → SSE stream back to browser.

## Getting started

### Prerequisites
- Node.js 20+
- Python 3.11+
- An Anthropic API key
- PostgreSQL (or just use SQLite for local dev — no setup required)

### Quick Start (Docker)
The easiest way to get started is using `docker-compose`.

```bash
cp backend/.env.example backend/.env # fill in ANTHROPIC_API_KEY
docker-compose up --build
```
Access the app at `http://localhost:5173`. Use the demo login: `admin@test.com` / `password123`.

### Backend (Manual)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, JWT_SECRET, DATABASE_URL
alembic upgrade head
python -m app.db.seed   # generates synthetic multi-tenant SaaS data with Faker
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_BASE_URL
npm run dev
```

### Tests
```bash
cd backend && pytest
```

## Performance & Latency

By utilizing Anthropic's streaming API directly for tool calls and textual responses, this architecture achieves excellent first-token latency.

To run the benchmark yourself:
```bash
cd backend
python tests/benchmark.py
```

## Documentation map

| File | What's in it |
|---|---|
| `ARCHITECTURE.md` | System diagram, component table, request lifecycle, latency budget, folder structure |
| `API_REFERENCE.md` | Endpoint specs, SSE event format, tool JSON schemas |
| `SECURITY.md` | JWT design, RBAC matrix, prompt-injection defenses, query validation rules |
| `CONTRIBUTING.md` | Local dev workflow, coding standards, commit conventions |
| `DEPLOYMENT.md` | Free-tier deployment steps for frontend, backend, and database |

## License

MIT
