"""What the queue ordering has actually learned, which is nothing, and the evidence.

`docs/PLAN.md` names two data assets that no amount of building fills: the attack corpus
and the record of decisions people actually made. Both are good schemas with almost
nothing in them, and the instruction is explicit -- build the pipes, never claim the
water.

`praetor/queueing.py` is the pipe. This is the honest reading of the tank.

    python eval/run_queue.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor.queueing import PRIOR, order  # noqa: E402


def human_decisions(db: Path) -> list[dict]:
    """Decisions a PERSON made. Not the agent's -- the agent's are not evidence about
    what a person would do, and using them would be the model grading its own homework."""
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT a.codes AS codes, 1 AS approved FROM approvals a").fetchall()
    except sqlite3.Error:
        return []
    return [{"codes": json.loads(r["codes"] or "[]"), "approved": bool(r["approved"])}
            for r in rows]


def pick(name: str) -> Path:
    fresh = ROOT / "out" / name
    return fresh if fresh.exists() else ROOT / "results" / name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="out/praetor.db")
    ap.add_argument("--exceptions", default="exc_constructed.jsonl")
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    exceptions_path = pick(args.exceptions)
    if not exceptions_path.exists():
        sys.exit(f"{exceptions_path} missing. Run: make rules")
    items = []
    for line in exceptions_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        items.append({"doc_id": row.get("doc_id"),
                      "codes": row.get("codes") or [],
                      "amount": row.get("amount_total")})

    decisions = human_decisions(ROOT / args.db)
    result = order(items, decisions)

    print("=" * 74)
    print(f"QUEUE ORDER over {len(items)} exceptions\n")
    print(f"  human decisions on record        {result.learned_from}")
    print(f"  finding types adjusted by them   {len(result.adjusted_codes)}")
    if result.is_prior_only:
        print("\n  Nothing has been learned. The order below is entirely the hand-written")
        print("  prior in praetor/queueing.py, and it is reported that way on purpose:")
        print("  a ranking presented as learned, from a record holding no decisions,")
        print("  would be the exact overclaim docs/PLAN.md warns about.")
        print("\n  This fills as people work the queue. It is a pipe, not a result.")
    else:
        print(f"  adjusted: {', '.join(result.adjusted_codes)}")

    print(f"\n  first {args.show} of {len(result.items)}:")
    for r in result.items[: args.show]:
        print(f"    {r.key:<12} {r.score:8.2f}  {', '.join(r.why)}")

    assert sorted(result.keys) == sorted(i["doc_id"] for i in items), \
        "ordering dropped an item"
    print(f"\n  every one of the {len(items)} exceptions is still in the queue "
          f"(ordering is a permutation, never a filter)")
    print("\nNo model was called. Cost Rs 0.")


if __name__ == "__main__":
    main()
