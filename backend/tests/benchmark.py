#!/usr/bin/env python3
"""
Latency benchmark for /api/copilot/query SSE endpoint.
Measures time-to-first-token across N concurrent requests and reports p50/p90/p95/p99.

Usage:
    python -m tests.benchmark --url http://localhost:6001 --n 30
"""

import asyncio
import argparse
import json
import time
import statistics
import httpx

QUERIES = [
    "What is our MRR trend for the last 6 months?",
    "What is our churn rate last quarter?",
    "List our top 5 customers by MRR.",
    "How many active users did we have last month?",
    "Compare MRR between enterprise and smb segments.",
]


async def measure_first_token(
    client: httpx.AsyncClient, url: str, token: str, query: str
) -> float:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    start = time.perf_counter()
    async with client.stream(
        "POST",
        f"{url}/api/copilot/query",
        headers=headers,
        json={"message": query},
        timeout=30,
    ) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:") and line.strip() != "data: [DONE]":
                return time.perf_counter() - start
    return time.perf_counter() - start  # fallback if no data line


async def run(url: str, n: int):
    # Login once
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{url}/api/auth/login",
            json={"email": "admin@test.com", "password": "password123"},
        )
        if r.status_code != 200:
            print(f"Login failed: {r.status_code} {r.text}")
            return
        token = r.json()["access_token"]

    print(f"Running {n} concurrent requests against {url} ...")
    queries = [QUERIES[i % len(QUERIES)] for i in range(n)]

    async with httpx.AsyncClient(http2=True) as client:
        tasks = [measure_first_token(client, url, token, q) for q in queries]
        latencies = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions
    good = [lat for lat in latencies if isinstance(lat, float)]
    errors = len(latencies) - len(good)

    if not good:
        print("All requests failed.")
        return

    good.sort()

    def pct(p: float) -> float:
        return good[int(len(good) * p / 100)]

    results = {
        "n": n,
        "errors": errors,
        "p50": round(pct(50), 3),
        "p90": round(pct(90), 3),
        "p95": round(pct(95), 3),
        "p99": round(pct(99), 3),
        "min": round(min(good), 3),
        "max": round(max(good), 3),
        "mean": round(statistics.mean(good), 3),
    }

    print(json.dumps(results, indent=2))
    passed = results["p95"] < 2.0
    print(
        f"\n{'PASS' if passed else 'FAIL'} — p95 first-token latency: "
        f"{results['p95']}s (target: <2.0s)"
    )

    with open("tests/benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results saved to tests/benchmark_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:6001")
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.n))
