# Documentation

An index. Everything here is written for a specific reader — start with the row that
matches why you are here.

## Architecture

| Document | For |
|---|---|
| [architecture/overview.md](architecture/overview.md) | System design and the request lifecycle |
| [architecture/metric-registry.md](architecture/metric-registry.md) | **The core idea.** How metrics are declared rather than coded, and how to add one |

## Reference

| Document | For |
|---|---|
| [reference/api.md](reference/api.md) | Endpoints, the SSE event contract, tool schemas |
| [../backend/evals/README.md](../backend/evals/README.md) | What the evals measure and how to add a case |

## Security

| Document | For |
|---|---|
| [../SECURITY.md](../SECURITY.md) | **Reporting a vulnerability**, and the known limitations |
| [security/design.md](security/design.md) | Token design, the RBAC matrix, injection defences and what they do not cover |

## Operations

| Document | For |
|---|---|
| [guides/deployment.md](guides/deployment.md) | Deploying it |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Local development and what review will ask about |

## Project

| Document | For |
|---|---|
| [../OVERHAUL_PLAN.md](../OVERHAUL_PLAN.md) | The engineering review this work came from: what was broken, what it would take to make this a product, and what was deliberately not built |
| [../CHANGELOG.md](../CHANGELOG.md) | What changed and why |

## Architecture decision records

`adr/` is empty. The decisions worth recording — a tool layer instead of text-to-SQL, a
declarative registry instead of hand-written SQL, MRR as a period-end measure, SSE over
WebSockets, evals as a CI gate — are currently explained in the modules that implement
them and in `OVERHAUL_PLAN.md`. Writing them up as ADRs is on the list; an empty
directory with a note is more honest than backdated records.
