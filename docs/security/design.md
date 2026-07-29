# Security — AI Co-Pilot for SaaS Analytics Platform

This document specifies the security controls that back the resume claims "JWT-authenticated services," "prompt-injection detection," "role-based access control," and "query validation at the request boundary." Treat it as a checklist during implementation and code review.

## 1. JWT design

**Claims**

```json
{
  "sub": "user_8f2a",
  "tenant_id": "tenant_412",
  "role": "analyst",
  "iat": 1750000000,
  "exp": 1750003600
}
```

- Signed with `HS256` for v1 (single backend service); document a migration path to `RS256`/JWKS if the system grows to multiple verifying services.
- Short access-token lifetime (15–30 minutes) plus a refresh-token flow. Refresh tokens are stored httpOnly, secure, same-site cookies — never in `localStorage`.
- `tenant_id` and `role` are set by the backend at login time from the user record, never accepted from the client.
- Every protected endpoint depends on a FastAPI dependency that verifies signature, expiry, and presence of required claims before anything else runs.

## 2. RBAC matrix

| Tool / endpoint | viewer | analyst | admin |
|---|---|---|---|
| `get_metric_trend` | ✅ | ✅ | ✅ |
| `get_churn_rate` | ✅ | ✅ | ✅ |
| `compare_segments` | ❌ | ✅ | ✅ |
| `get_top_customers` | ❌ | ✅ | ✅ |
| `list_active_alerts` | ❌ | ❌ | ✅ |
| `/api/copilot/query` | ✅ | ✅ | ✅ |
| `/api/admin/users` | ❌ | ❌ | ✅ |

Implementation rule: the RBAC check happens **before** the request reaches the orchestrator, and a second check happens **again** inside the query validator right before execution. Checking twice (defense in depth) means a bug in one layer doesn't silently become a privilege escalation.

## 3. Prompt-injection detection

**Threat model:** a user (or data smuggled in through a tool result, in future versions with retrieval) tries to override the system prompt, exfiltrate it, or convince the model to call a tool outside their role/tenant scope.

**Layered defenses:**

1. **Heuristic pre-filter.** Before any text reaches Claude, scan for structural patterns associated with instruction-override attempts (for example: text that tries to redefine the assistant's role or instructions, or that asks the assistant to reveal or disregard its system prompt). Flagged input is logged and either soft-blocked (answered with a generic clarification request) or passed through with a flag for downstream handling — tune this based on false-positive rate during testing.
2. **System prompt hardening.** Structure the system prompt so user input is clearly delimited as data (e.g. wrapped in explicit tags), the tool allow-list is stated plainly, and the model is told that any instructions appearing inside user text or tool results are data, not commands.
3. **Model self-flagging.** Ask Claude, as part of the system instructions, to note if a request looks like it's trying to manipulate the assistant's behavior rather than ask a genuine analytics question, and surface that as a soft signal to the orchestrator.
4. **Authorization is not advisory.** The critical property: even a fully successful injection that gets the model to "decide" to call `list_active_alerts` as a `viewer` does nothing, because the validator layer re-checks role and tenant before touching the database. The injection guard reduces noise and catches obvious attempts early; it is not the thing standing between an attacker and the data — the validator is.
5. **Logging and review.** Every flagged input is logged with `user_id`, `tenant_id`, timestamp, and a hash of the input (not necessarily the raw text, depending on your privacy stance) for periodic review and heuristic tuning.

Avoid building or publishing a list of example bypass phrases in the repo — write tests against categories of behavior (e.g. "attempts to redefine role," "attempts to request out-of-scope tool") rather than a literal phrase library, since a phrase library is more useful to an attacker than to a defender.

## 4. Query validation at the request boundary

This is the layer that makes the system safe even if every layer above it fails.

- **Allow-list, not deny-list.** The model can only ever request one of a small, explicitly defined set of tool functions. There is no "execute arbitrary SQL" tool, ever.
- **Typed arguments.** Every tool's arguments are defined as a Pydantic model (e.g. `metric: Literal["mrr", "arr", "active_users"]`, `start_date: date`, `granularity: Literal["day","week","month"]`). Anthropic's structured tool-use already constrains the shape, but the backend re-validates independently rather than trusting the model's JSON.
- **Tenant injection, not tenant trust.** `tenant_id` for the SQL query comes from the verified JWT, not from the tool arguments, even if the model includes one.
- **Parameterized queries only.** All database access goes through SQLAlchemy Core/ORM with bound parameters. No string formatting or concatenation into SQL, ever — this is non-negotiable even for "obviously safe" values like dates.
- **Row and range caps.** Every read has a maximum row limit and a maximum date range, to bound both cost and the size of data that could be exfiltrated by a single call.
- **Fail closed.** If validation fails for any reason (unknown tool name, bad argument shape, role/tenant mismatch), return a structured error to the orchestrator rather than a partial result — the orchestrator turns this into a graceful "I can't answer that" rather than surfacing raw errors to the user.

## 5. Secrets and configuration

- All secrets (Anthropic API key, JWT signing key, database URL) come from environment variables, never committed. `.env.example` files list variable names with placeholder values only.
- `.env` is in `.gitignore` from the first commit.
- Use a secrets manager or the hosting platform's environment variable store in production (Render/Fly.io/Vercel all support this on free tiers).

## 6. Dependency hygiene

- Python: run `pip-audit` in CI.
- JavaScript: run `npm audit` in CI.
- Pin major versions in `pyproject.toml` / `package.json`; let CI flag outdated/vulnerable transitive dependencies rather than auto-upgrading silently.

## 7. Test coverage required for this document to be considered "implemented"

- JWT: expired token rejected, tampered signature rejected, missing claim rejected.
- RBAC: each role × each tool/endpoint combination in the matrix above has an explicit test (positive and negative).
- Injection guard: tests organized by category of manipulation attempt, not literal strings, asserting the request is flagged/blocked/logged as expected.
- Query validator: out-of-allow-list tool name rejected; tampered tenant_id in arguments is ignored in favor of JWT tenant_id; row cap enforced; SQL injection attempt via a string argument (e.g. a metric name containing `; DROP TABLE`) is rejected by type validation before it ever reaches a query.
