# Security policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report privately through [GitHub Security Advisories](https://github.com/adityamhaske/AI-Co-Pilot-for-SaaS-Analytics-Platform/security/advisories/new).

Please include what you found, how to reproduce it, and what an attacker could do with
it. A proof of concept helps but is not required.

**What to expect:** acknowledgement within 3 working days, an assessment within 10, and
credit in the release notes unless you would rather not be named. This is a personal
open-source project with no bounty programme.

## Scope

In scope — the code in this repository:

- Authentication and session handling (`backend/app/core/security.py`, `core/tokens.py`, `api/auth.py`)
- Authorisation and role enforcement (`core/rbac.py`, `orchestrator/tools.py`)
- **Cross-tenant data access** through any path, which is the highest-severity class here
- Prompt injection that reaches a tool the caller's role does not permit, or that
  causes data from another tenant to be disclosed
- SQL injection, SSRF, XSS
- Anything allowing unbounded spend on the operator's Anthropic account

Out of scope:

- The synthetic seed data and its published demo credentials
- Missing rate limits on a self-hosted deployment you control
- Findings that require a valid `admin` token for the same tenant
- Automated scanner output with no demonstrated impact
- Denial of service by volume against a deployment you control

## Known limitations

Stated plainly, because a security policy that implies more protection than exists is
itself a hazard:

- **The prompt-injection guard is a heuristic, not a control.** Five regexes in
  `app/guard/injection_guard.py`. It is telemetry. The real controls are RBAC-scoped
  tool exposure, double authorisation, and tenant scoping the model cannot influence.
  Treat a regex bypass as expected, not as a vulnerability; a bypass that reaches an
  unauthorised *tool* is a vulnerability.
- **Tool results are not sanitised.** Data from the database — a customer name, an event
  type — enters the model's context. Attacker-controlled content reaching those columns
  is an indirect injection vector. Blast radius is limited to the caller's own tenant.
- **Tenant isolation is enforced in the application**, in `app/metrics/compiler.py`, not
  by Postgres row-level security. A bug in the compiler is not caught by a second layer.
  RLS is planned; see `OVERHAUL_PLAN.md`.
- **No signup, so no account-recovery or email-verification surface** exists to attack.
- **Not audited.** No penetration test or third-party review has been performed.

## For operators

- `JWT_SECRET` must be at least 32 characters and is validated at startup; the app
  refuses to boot on a missing, short or placeholder value.
- Set `ENVIRONMENT=production`. It rejects SQLite, requires an API key, and disables the
  interactive API docs.
- `CORS_ORIGINS` must list your exact frontend origin. A wildcard is rejected.
- Serve over HTTPS. The refresh cookie is `Secure`, so it will not be sent over plain
  HTTP outside localhost.
- Set `DAILY_COST_LIMIT_USD` for your tolerance. The default is $2 per user per day.
