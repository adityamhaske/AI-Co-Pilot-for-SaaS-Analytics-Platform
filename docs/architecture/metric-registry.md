# Adding a metric

Metrics are declared, not coded. One YAML file in
`backend/app/metrics/definitions/` gives you all of:

- the SQL, compiled per dialect
- the argument-validation model
- the tool schema the model sees, including the metric enum and glossary
- the RBAC scope

You should not need to touch Python to add a metric.

## Why it works this way

Before the registry, a metric's semantics lived in hand-written SQL in
`query_validator.py` and its tool schema lived in a separate hand-maintained list in
`orchestrator/tools.py`. Nothing kept the two in step, and two things went wrong:

- `granularity` was declared in the tool schema, advertised to the model, validated on
  the way in — and then ignored by every handler. Users asked for daily trends and
  silently got monthly buckets.
- **Three** different definitions of MRR existed in one file: a point-in-time sum for
  trends, and two `status == 'active'` variants for segment comparison and customer
  ranking. "MRR trend" and "compare MRR by segment" returned numbers that could not be
  reconciled.

Both are structurally impossible now. `tests/test_registry.py` asserts that every metric
in a tool enum resolves to a real definition, and `tests/test_metrics.py` asserts that a
segment comparison sums back to the corresponding snapshot.

## The shortest possible metric

```yaml
name: paid_invoices
label: Paid Invoices
description: >
  Count of invoices marked paid, by issue date. Used to sanity-check billing against
  recognised revenue.
unit: count
kind: row_count
minimum_role: analyst
supports: [trend, snapshot]

source:
  model: invoice
  timestamp_column: issue_date
  entity_column: customer_id
  filters:
    status: paid
```

Drop that in `definitions/`, restart, and `paid_invoices` appears in the
`get_metric_trend` and `get_metric_value` enums for analysts and admins — but not for
viewers.

## Fields

| Field | Meaning |
|---|---|
| `name` | Identifier the model uses. Snake case. Must be unique. |
| `label` | Human-readable name, shown in chart legends. |
| `description` | **The model reads this to choose a metric.** Say what is counted and what is excluded. Vague descriptions cause wrong tool calls. |
| `unit` | `count`, `currency_usd` or `ratio`. Drives rounding and UI formatting. |
| `kind` | See below. |
| `minimum_role` | `viewer`, `analyst` or `admin`. |
| `supports` | Which query shapes may use it: `trend`, `snapshot`, `compare`. An empty list makes it a building block, usable only by other metrics. |
| `evaluate_at` | For interval kinds: `period_end` (default), `period_start`, or `overlap`. |

### Kinds

| Kind | Computes | Requires |
|---|---|---|
| `point_in_time_sum` | Sum of a value over rows valid at an instant — MRR. | `value_column`, `interval_start` |
| `point_in_time_count` | Count of rows valid at an instant — active subscriptions. | `interval_start` |
| `distinct_count` | Distinct values among rows timestamped in the period — active users. | `timestamp_column`, `distinct_column` |
| `row_count` | Rows timestamped in the period — new signups. | `timestamp_column` |
| `derived` | Another metric times a constant — ARR. | `base`, `factor` |
| `ratio` | One metric over another — churn rate. | `numerator`, `denominator` |

### Stock vs flow

This is the distinction that causes most metric bugs, so it is worth stating plainly.

A **stock** has a value at an instant. MRR on 31 March is a number; "MRR during March"
is not well defined. Stocks use the `point_in_time_*` kinds and are measured at
`period_end` by default, matching the industry convention ("MRR as of month end"). A
subscription that cancels on 15 March is in February's closing MRR but not March's.

A **flow** accumulates over a window. New signups in March is a count over the whole
month. Flows use `row_count` or `distinct_count`.

`evaluate_at: period_start` exists for churn's denominator: the population at risk when
the window opened, not everyone who was active at any point during it.

## Composing metrics

`churn_rate` is defined entirely in terms of two other declared metrics:

```yaml
name: churn_rate
kind: ratio
numerator: churned_subscriptions
denominator: active_subscriptions_at_start
```

Its components declare `supports: []`, so no tool advertises them — they exist only to
be composed. A snapshot of a ratio returns both terms alongside the quotient, because a
bare `0.05` is not checkable but "3 of 60" is.

## Guardrails

The loader validates every definition at import, so a mistake stops the app from
starting rather than surfacing as a wrong answer months later:

- `model` must be one of the allow-listed models in `schema.py`. A definition cannot
  point the compiler at an arbitrary table.
- Every referenced column must exist on that model. A typo like `creatd_at` fails at
  startup.
- Each `kind` must have the fields it needs.
- `base`, `numerator` and `denominator` must resolve, and must not form a cycle.
- `minimum_role` must be a real role.

Tenant scoping is not your responsibility and is not something a definition can opt out
of: `compiler._base_filters` is the only path by which a query is built, and it always
applies the tenant predicate.

## Two independent gates

A caller must pass both:

1. **Tool access** — `ROLE_PERMISSIONS` in `app/core/rbac.py` gates the query *shape*.
2. **Metric access** — `minimum_role` on the definition gates the *metric*.

Widening one never silently widens the other. The model is only ever shown the tools,
and the metric enums inside them, that the caller may actually use.

## Checklist

1. Write the YAML file.
2. Add a test in `tests/test_metrics.py` asserting an exact number against the fixture
   in `tests/conftest.py`. Do not skip this — a metric with no numeric assertion is a
   metric nobody has checked.
3. Run `pytest`. The registry tests will fail if the definition is malformed.
4. If the metric needs a shape that does not exist yet, that is a change to
   `app/metrics/queries.py` — and worth discussing first.
