# Evals

A natural-language analytics tool is only worth anything if it picks the right query.
These evals measure that, against questions with known correct answers.

```bash
cd backend
export ANTHROPIC_API_KEY=sk-...
PYTHONPATH=. python -m evals.runner
```

```
PYTHONPATH=. python -m evals.runner --category rbac       # one category
PYTHONPATH=. python -m evals.runner --case current_mrr    # one case
PYTHONPATH=. python -m evals.runner --repeat 5            # sample for variance
PYTHONPATH=. python -m evals.runner --json results.json   # full transcript
```

## What is measured, and what is not

The model is the only non-deterministic part of the system, so that is what these
measure: **given a question, does it choose the right tool with the right arguments, and
does it decline when it should?**

Metric arithmetic is *not* measured here. It is deterministic, so it is tested exactly
and without an API key in `tests/test_metrics.py`. Mixing the two would make a flaky
number out of something that should be exact.

Three independent graders run per case, so a report tells you *where* it broke:

| Grader | Question |
|---|---|
| `tool` | Was the expected tool called, with the expected arguments? |
| `value` | Did a tool result actually contain the expected number? |
| `answer` | Does the final text satisfy the case's contains / not-contains / declines constraints? |

No model-as-judge. A grader that used an LLM would make the accuracy number depend on
the thing being measured.

## Categories

| Category | What it probes |
|---|---|
| `direct` | Plainly-worded questions. Should be near 100%; anything less is a real problem. |
| `granularity` | "day by day", "weekly" — the parameter that used to be advertised and then silently ignored. |
| `indirect` | Vocabulary the schema does not use: "am I losing customers", "worth the most". |
| `multi_tool` | Questions needing two calls, which is also the parallel-tool-call path. |
| `grounding` | Questions the data cannot answer. The model must decline, not estimate. |
| `rbac` | Questions whose tool is not in that role's schema at all. |
| `adversarial` | Instructions embedded in the question: role override, cross-tenant requests, "just estimate it". |

The last three matter most. A wrong number is a bug; a *confident fabricated* number, or
one tenant's data reaching another, is a different category of failure.

## Dates are not graded

Cases assert `metric` and `granularity` but leave date ranges free. Several ranges are
defensible for "the last 6 months", and pinning them would measure prompt-phrasing luck
rather than correctness.

## The fixture

`fixtures.py` builds a fixed dataset whose answers are computed by hand:

```
enterprise   5 customers x $1,000   active
smb          3 customers x   $200   active
midmarket    2 customers x   $500   cancelled 40 days ago

mrr 5,600   arr 67,200   enterprise 5,000   smb 600   churn (quarter) 0.2
```

Every date derives from *today*, so these stay correct as the calendar moves.

Those expected values are themselves verified against the metric layer in
`tests/test_evals.py`, on every commit. Without that, the evals could measure agreement
with a wrong answer.

## In CI

- **Every commit** — the harness runs without an API key: dataset integrity (every case
  names a real tool, role and metric, and asserts *something*), the fixture's expected
  values, and the graders.
- **Nightly and on demand** — `.github/workflows/evals.yml` runs the full set against
  the live API and fails below `--threshold` (default 85%).

Nightly matters because model behaviour drifts. A number measured once at launch tells
you nothing three months later.

## Adding a case

```yaml
- id: some_new_question
  question: Ask it the way a real user would.
  role: viewer
  category: indirect
  expect_tool:
    name: get_metric_value
    args: { metric: mrr }
  expect_value: mrr          # a key in fixtures.EXPECTED
  expect_answer:
    indicates_inability: false
```

`tests/test_evals.py` will reject a case that names an unknown tool, an unreachable
metric, a role that cannot use that tool, or that asserts nothing at all.

## Interpreting a run

Report accuracy alongside the model id and the date. An eval number without those is
not reproducible. Treat `direct` below 100% as a bug in the tool descriptions rather
than a model failure — the description is the only thing the model has to go on when
choosing between `mrr` and `arr`.
