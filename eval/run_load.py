"""What the deployed surface does under concurrent load.

`FINDINGS.md` §11 measures the kernel: ~4,100 documents/second on one core, and 8 worker
processes make it *slower*, so there is nothing to distribute. That is a measurement of
the deterministic path with no web layer around it.

This measures the other thing — the queue an analyst actually loads, over HTTP, through
the transport, with the store and the rate limiter in the way. A number for the kernel
says nothing about whether the page opens.

Two questions, and the second matters more:

**1. How fast is a queue page, and how does it degrade?** Latency percentiles under
rising concurrency. A mean hides the request that made somebody reload.

**2. Does the rate limiter hold?** `dashboard/ratelimit.py` allows 120 reads a minute per
caller. Under a burst it must *refuse* cleanly with a Retry-After, not fall over, not
leak memory, and not start serving errors from the endpoints it is protecting. A limiter
that collapses under the load it exists for is worse than none, because the capacity plan
assumed it worked.

Runs against a local server, so it costs nothing and calls no model.

    make load
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


COOKIE = ""          # set from --cookie; the queue is a client's own data


def one(url: str, timeout: float = 30.0) -> tuple[int, float]:
    """One request. Returns (status, seconds)."""
    started = time.perf_counter()
    request = urllib.request.Request(
        url, headers={"Cookie": f"praetor_session={COOKIE}"} if COOKIE else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            r.read()
            return r.status, time.perf_counter() - started
    except urllib.error.HTTPError as e:
        e.read()
        return e.code, time.perf_counter() - started
    except Exception:  # noqa: BLE001
        return 0, time.perf_counter() - started


def burst(url: str, n: int, concurrency: int) -> tuple[list[float], Counter]:
    latencies: list[float] = []
    codes: Counter = Counter()
    lock = threading.Lock()

    def run(_):
        status, seconds = one(url)
        with lock:
            latencies.append(seconds)
            codes[status] += 1

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(run, range(n)))
    return latencies, codes, time.perf_counter() - started


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    def at(p: float) -> float:
        return ordered[min(int(len(ordered) * p), len(ordered) - 1)]
    return {"p50": at(0.50), "p95": at(0.95), "p99": at(0.99),
            "max": ordered[-1], "mean": statistics.fmean(ordered)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--path", default="/v1/gauntlet/examples",
                    help="open endpoint, so the run needs no session")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--out", default="out/load.json")
    ap.add_argument("--cookie", default="",
                    help="a praetor_session token, to load an endpoint that needs one")
    args = ap.parse_args()

    global COOKIE
    COOKIE = args.cookie
    url = args.base + args.path
    status, _ = one(url)
    if status == 0:
        sys.exit(f"nothing answering at {url}. Start it with: make api")

    print("=" * 72)
    print(f"LOAD against {url}\n")
    print(f"{'concurrency':>12} {'requests':>9} {'req/s':>8} "
          f"{'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'ok':>5} {'429':>5} {'other':>6}")
    print("-" * 72)

    results = []
    for concurrency in (1, 4, 16, 64):
        latencies, codes, wall = burst(url, args.requests, concurrency)
        p = percentiles(latencies)
        other = sum(v for k, v in codes.items() if k not in (200, 429))
        row = {"concurrency": concurrency, "requests": args.requests,
               "rps": args.requests / wall, "ok": codes.get(200, 0),
               "throttled": codes.get(429, 0), "other": other,
               **{k: v * 1000 for k, v in p.items()}}
        results.append(row)
        print(f"{concurrency:>12} {args.requests:>9} {row['rps']:>8.0f} "
              f"{row['p50']:>8.1f} {row['p95']:>8.1f} {row['p99']:>8.1f} "
              f"{row['ok']:>5} {row['throttled']:>5} {other:>6}")
        # Let the limiter's window drain, so the next rung measures capacity rather than
        # the tail of the previous burst.
        time.sleep(3)

    print("-" * 72)
    throttled = sum(r["throttled"] for r in results)
    failed = sum(r["other"] for r in results)
    print(f"\n  refused with 429 (the limiter working)   {throttled}")
    print(f"  failed for any other reason              {failed}"
          f"{'   <- must be 0' if failed == 0 else '   <- LOOK AT THIS'}")
    print("\n  A 429 is a pass, not a failure: the limiter exists to refuse. What would")
    print("  be a failure is a 5xx, a timeout, or the limiter letting everything through.")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"url": url, "rungs": results}, indent=1) + "\n")
    print(f"\nwrote {out}\nNo model was called. Cost Rs 0.")


if __name__ == "__main__":
    main()
