#!/usr/bin/env python3
"""Run the golden-question evals against the real model.

    python -m evals.runner                    # everything
    python -m evals.runner --category rbac    # one category
    python -m evals.runner --case mrr_trend_6_months
    python -m evals.runner --repeat 3         # sample the same case several times

Needs a real ANTHROPIC_API_KEY: the point is to measure whether the model picks the
right tool with the right arguments, which a mock cannot tell you. Metric arithmetic is
covered separately and deterministically by tests/test_metrics.py.

Exits non-zero if accuracy falls below --threshold, so CI can gate on it.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

DATASET = Path(__file__).parent / "dataset.yaml"


def load_cases(path: Path = DATASET) -> list[dict]:
    return yaml.safe_load(path.read_text())


async def run_case(case: dict, tenant_id: str) -> dict:
    """Drive the real orchestrator and capture what it did."""
    from app.db.session import SessionLocal
    from app.streaming.sse import stream_orchestrator
    from evals import fixtures

    # Imported lazily so `--list` works without a database or an API key.
    tool_calls: list[dict] = []
    text_parts: list[str] = []
    errors: list[str] = []

    db = SessionLocal()
    started = time.perf_counter()
    try:
        async for chunk in stream_orchestrator(
            db, tenant_id, case["role"], case["question"]
        ):
            body = chunk.removeprefix("data: ").strip()
            if not body or body == "[DONE]":
                continue
            event = json.loads(body)
            kind = event.get("type")
            if kind == "token":
                text_parts.append(event["text"])
            elif kind == "tool_result":
                tool_calls.append(
                    {
                        "name": event["name"],
                        "input": event.get("input") or {},
                        "result": event.get("data"),
                    }
                )
            elif kind == "error":
                errors.append(event["message"])
    finally:
        db.close()

    expected_value = None
    if case.get("expect_value"):
        expected_value = fixtures.EXPECTED[case["expect_value"]]

    return {
        "answer": "".join(text_parts),
        "tool_calls": tool_calls,
        "errors": errors,
        "expected_value": expected_value,
        "latency_s": round(time.perf_counter() - started, 2),
    }


async def run_all(cases: list[dict], concurrency: int, tenant_id: str) -> list[dict]:
    from evals.graders import grade_case

    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def one(case: dict) -> None:
        async with semaphore:
            try:
                run = await run_case(case, tenant_id)
            except Exception as exc:  # a crash is a failure, not a lost data point
                results.append(
                    {
                        "id": case["id"],
                        "category": case.get("category", "uncategorised"),
                        "question": case["question"],
                        "role": case["role"],
                        "crashed": str(exc),
                        "verdicts": [
                            {"name": "run", "passed": False, "reason": str(exc)}
                        ],
                        "passed": False,
                        "latency_s": None,
                    }
                )
                return

            verdicts = grade_case(case, run)
            results.append(
                {
                    "id": case["id"],
                    "category": case.get("category", "uncategorised"),
                    "question": case["question"],
                    "role": case["role"],
                    "answer": run["answer"],
                    "tool_calls": [
                        {"name": c["name"], "input": c["input"]}
                        for c in run["tool_calls"]
                    ],
                    "errors": run["errors"],
                    "verdicts": [
                        {"name": v.name, "passed": v.passed, "reason": v.reason}
                        for v in verdicts
                    ],
                    "passed": all(v.passed for v in verdicts),
                    "latency_s": run["latency_s"],
                }
            )

    await asyncio.gather(*(one(c) for c in cases))
    order = {c["id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r["id"]])
    return results


def report(results: list[dict], threshold: float) -> bool:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = passed / total if total else 0.0

    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r)

    print()
    print("=" * 74)
    print(f"  {passed}/{total} cases passed   ({accuracy:.1%})")
    print("=" * 74)

    print("\nBy category")
    for category in sorted(by_category):
        rows = by_category[category]
        ok = sum(1 for r in rows if r["passed"])
        bar = "#" * round(20 * ok / len(rows))
        print(
            f"  {category:<14} {ok:>2}/{len(rows):<3} {bar:<20} {ok / len(rows):>6.0%}"
        )

    # Which grader is failing tells you where the weakness is.
    grader_totals: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        for v in r["verdicts"]:
            grader_totals[v["name"]].append(v["passed"])
    print("\nBy grader")
    for name in sorted(grader_totals):
        outcomes = grader_totals[name]
        ok = sum(outcomes)
        print(f"  {name:<14} {ok:>2}/{len(outcomes):<3} {ok / len(outcomes):>6.0%}")

    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\nFailures ({len(failures)})")
        for r in failures:
            print(f"\n  {r['id']}  [{r['category']}, role={r['role']}]")
            print(f"    Q: {r['question'].strip()[:100]}")
            for v in r["verdicts"]:
                if not v["passed"]:
                    print(f"    {v['name']}: {v['reason']}")
            if r.get("tool_calls"):
                for c in r["tool_calls"]:
                    print(f"    called: {c['name']}({json.dumps(c['input'])})")
            if r.get("answer"):
                print(f"    said: {r['answer'].strip()[:160]}")

    latencies = [r["latency_s"] for r in results if r.get("latency_s")]
    if latencies:
        latencies.sort()
        p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
        print(
            f"\nLatency  median {statistics.median(latencies):.1f}s   "
            f"p95 {p95:.1f}s   max {max(latencies):.1f}s"
        )

    print(
        f"\nThreshold {threshold:.0%} — {'PASS' if accuracy >= threshold else 'FAIL'}"
    )
    return accuracy >= threshold


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", help="only run one category")
    parser.add_argument("--case", help="only run one case id")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--json", type=Path, help="write full results here")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    args = parser.parse_args()

    cases = load_cases()

    if args.category:
        cases = [c for c in cases if c.get("category") == args.category]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        print("No cases matched.", file=sys.stderr)
        return 2

    if args.list:
        for c in cases:
            print(f"{c['id']:<32} {c.get('category',''):<14} {c['role']}")
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key == "test":
        print(
            "ANTHROPIC_API_KEY is not set to a real key.\n"
            "These evals measure the model's tool choice, so they need a live API call.\n"
            "Metric arithmetic is covered without an API key by tests/test_metrics.py.",
            file=sys.stderr,
        )
        return 2

    if args.repeat > 1:
        cases = [c for c in cases for _ in range(args.repeat)]

    from app.db.session import SessionLocal
    from evals import fixtures

    db = SessionLocal()
    try:
        fixtures.build(db)
    finally:
        db.close()

    print(f"Running {len(cases)} cases against tenant {fixtures.EVAL_TENANT} ...")
    results = asyncio.run(run_all(cases, args.concurrency, fixtures.EVAL_TENANT))
    ok = report(results, args.threshold)

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nFull results written to {args.json}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
