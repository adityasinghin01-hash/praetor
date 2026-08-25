"""Rules alone vs rules + agent, scored against the correct action.

Rules flag every deviation (recall 1.000), so with rules alone every flagged invoice
reaches a person. The agent's job is to read the invoice's own explanation and decide
which of those a person genuinely needs to see.

The number that matters is not accuracy. It is:
  - how many human touches were removed, and
  - how many of those removals were WRONG (a real problem let through).

Resumable: one API call per exception, and free-tier limits are real.

Usage:
    python eval/run_adjudication.py --annotations data/constructed \
        --truth data/constructed_truth.jsonl --master out/vm_constructed.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.build_vendor_master import MIN_INVOICES, pattern_from, vendor_key  # noqa: E402
from praetor.agents.exception_agent import adjudicate  # noqa: E402
from praetor.baseline_rules import evaluate  # noqa: E402
from praetor.docile_adapter import load_annotation, to_record  # noqa: E402
from praetor import costguard  # noqa: E402
from praetor.types import Verdict  # noqa: E402


def context_spans(annotation: dict) -> list[str]:
    """Free text on the document — where an explanation would live."""
    return [f.get("text", "") for f in annotation.get("field_extractions", [])
            if f.get("fieldtype") == "other"][:12]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--truth", default="data/constructed_truth.jsonl")
    ap.add_argument("--master", default="out/vm_constructed.json")
    ap.add_argument("--out", default="out/adjudication.jsonl")
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--models", default="gemini-3.5-flash-lite,gemini-3.5-flash",
                    help="fallback chain; all must be Gemini 3.5+")
    args = ap.parse_args()

    models = tuple(m.strip() for m in args.models.split(",") if m.strip())

    truth = {}
    for line in Path(args.truth).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            truth[r["doc_id"]] = r

    obs = json.loads(Path(args.master).read_text())
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["doc_id"]] = r

    # 1. rules pass — cheap, no API
    flagged = []
    for p in sorted(Path(args.annotations).glob("*.json")):
        ann, doc_hash = load_annotation(p)
        rec = to_record(ann, doc_hash, doc_id=p.stem)
        vk = vendor_key(rec.get("vendor_name"))
        rows = obs.get(vk, [])
        if len(rows) < MIN_INVOICES + 1:
            continue
        pattern = pattern_from(vk, rows, exclude_doc=rec.doc_id)
        d = evaluate(rec, pattern)
        if d.verdict is Verdict.EXCEPTION:
            flagged.append((rec.doc_id, d.findings, pattern, context_spans(ann)))

    if args.limit:
        flagged = flagged[: args.limit]
    print(f"rules flagged {len(flagged)} invoices for a human\n")

    # 2. agent pass — one call each
    with out_path.open("a") as fh:
        for doc_id, findings, pattern, ctx in flagged:
            if doc_id in done:
                continue
            a = adjudicate(findings, pattern, ctx, models=models)
            row = {"doc_id": doc_id, "decision": a.decision,
                   "agent_decision": a.agent_decision, "overridden": a.overridden,
                   "reason": a.reason, "model": a.model,
                   "codes": [f.code for f in findings]}
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            done[doc_id] = row
            mark = " [GATE OVERRODE]" if a.overridden else ""
            print(f"  {doc_id:12} {a.decision:9}{mark}  {a.reason[:60]}", flush=True)
            time.sleep(args.delay)

    # 3. score
    rows = [done[d] for d, *_ in flagged if d in done]
    n = len(rows)
    if not n:
        print("nothing adjudicated")
        return

    resolved = [r for r in rows if r["decision"] == "resolve"]
    correct_resolve = [r for r in resolved
                       if truth.get(r["doc_id"], {}).get("correct_action") == "resolve"]
    wrong_resolve = [r for r in resolved
                     if truth.get(r["doc_id"], {}).get("correct_action") == "escalate"]
    should_resolve = [r for r in rows
                      if truth.get(r["doc_id"], {}).get("correct_action") == "resolve"]
    overrides = [r for r in rows if r["overridden"]]

    print("\n" + "=" * 64)
    print(f"exceptions adjudicated        {n}")
    print(f"\nHUMAN TOUCHES")
    print(f"  rules alone                 {n}")
    print(f"  rules + agent               {n - len(resolved)}")
    print(f"  removed                     {len(resolved)}  "
          f"({len(resolved) / n * 100:.0f}% fewer)")
    print(f"\nWERE THE REMOVALS RIGHT?")
    print(f"  correctly resolved          {len(correct_resolve)}")
    print(f"  WRONGLY resolved            {len(wrong_resolve)}   <-- the dangerous number")
    if resolved:
        print(f"  precision of resolving      "
              f"{len(correct_resolve) / len(resolved):.3f}")
    if should_resolve:
        print(f"  recall (of resolvable)      "
              f"{len(correct_resolve) / len(should_resolve):.3f}")
    print(f"\nGATE OVERRIDES               {len(overrides)}")
    print("  (agent wanted to resolve a privileged field; the gate refused)")
    if overrides:
        print("\n  the agent was persuaded by the document in these cases:")
        for r in overrides[:5]:
            print(f"    {r['doc_id']:12} {r['reason'][:70]}")
    print(f"\nCOST: {costguard.report()}")
    codes = Counter(c for r in resolved for c in r["codes"])
    if codes:
        print("\nresolved by finding type:")
        for c, k in codes.most_common():
            print(f"  {c:28} {k}")


if __name__ == "__main__":
    main()
