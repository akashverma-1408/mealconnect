"""Tiny load test: concurrent GETs against catalogue endpoints, reports latency percentiles.

    python scripts/benchmark.py http://localhost:8001 http://localhost:8002 --requests 400

Uses only httpx (already a backend dependency) and a thread pool.
"""

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

PATHS = [
    "/api/v1/restaurants?city=Pune",
    "/api/v1/restaurants?sort=-avg_rating&page=1&size=12",
    "/api/v1/restaurants/1/menu",
    "/api/v1/restaurants/3/menu",
    "/api/v1/search/menu-items?q=paneer",
]


def run(base: str, total: int, concurrency: int) -> dict:
    client = httpx.Client(base_url=base, timeout=10)
    for p in PATHS:  # warm-up (fills the cache when enabled, opens DB connections)
        client.get(p).raise_for_status()

    def one(i: int) -> float:
        start = time.perf_counter()
        res = client.get(PATHS[i % len(PATHS)])
        res.raise_for_status()
        return (time.perf_counter() - start) * 1000

    t0 = time.perf_counter()
    with ThreadPoolExecutor(concurrency) as pool:
        latencies = sorted(pool.map(one, range(total)))
    elapsed = time.perf_counter() - t0
    q = statistics.quantiles(latencies, n=100)
    return {
        "p50_ms": round(q[49], 1),
        "p95_ms": round(q[94], 1),
        "p99_ms": round(q[98], 1),
        "rps": round(total / elapsed),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--requests", type=int, default=400)
    ap.add_argument("--concurrency", type=int, default=20)
    args = ap.parse_args()
    for url in args.urls:
        print(url, run(url, args.requests, args.concurrency))
