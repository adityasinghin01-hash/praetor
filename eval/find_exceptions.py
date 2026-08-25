"""Discover real exceptions: documents that deviate from their own supplier's norm.

These are not injected. Each one is a genuine inconsistency between a real invoice
and the pattern derived from that same supplier's other real invoices, judged
leave-one-out so a document never contributes to the norm it is measured against.

Usage:
    python eval/find_exceptions.py --master out/vendor_master.json \
        --annotations data/docile/annotations --out out/exceptions.jsonl
    python eval/find_exceptions.py ... --sample 30 --blind out/blind_sample.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.build_vendor_master import MIN_INVOICES, pattern_from, vendor_key  # noqa: E402
from praetor.baseline_rules import evaluate  # noqa: E402
from praetor.docile_adapter import load_annotation, to_record  # noqa: E402
from praetor.types import Verdict  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="out/vendor_master.json")
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--out", default="out/exceptions.jsonl")
    ap.add_argument("--sample", type=int, help="write N for blind human labelling")
    ap.add_argument("--blind", default="out/blind_sample.csv")
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    obs: dict[str, list[dict]] = json.loads(Path(args.master).read_text())

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stats = Counter()
    codes = Counter()
    rows_out: list[dict] = []

    with out_path.open("w") as fh:
        for p in sorted(Path(args.annotations).glob("*.json")):
            ann, doc_hash = load_annotation(p)
            rec = to_record(ann, doc_hash, doc_id=p.stem)
            vk = vendor_key(rec.get("vendor_name"))
            rows = obs.get(vk, [])

            if len(rows) < MIN_INVOICES + 1:
                stats["skipped_thin_vendor"] += 1
                continue

            pattern = pattern_from(vk, rows, exclude_doc=rec.doc_id)
            decision = evaluate(rec, pattern)
            stats["evaluated"] += 1

            if decision.verdict is Verdict.PASS:
                stats["pass"] += 1
                continue

            stats["exception"] += 1
            for c in decision.codes:
                codes[c] += 1

            row = {
                "doc_id": rec.doc_id,
                "vendor_key": vk,
                "n_peer_invoices": pattern.n_invoices,
                "codes": decision.codes,
                "findings": [
                    {"code": f.code, "field": f.field, "detail": f.detail}
                    for f in decision.findings
                ],
            }
            fh.write(json.dumps(row) + "\n")
            rows_out.append(row)

    ev = stats["evaluated"] or 1
    print(f"evaluated            {stats['evaluated']}")
    print(f"skipped (thin vendor){stats['skipped_thin_vendor']:>7}")
    print(f"passed               {stats['pass']}  ({stats['pass'] / ev * 100:.1f}%)")
    print(f"exceptions           {stats['exception']}  ({stats['exception'] / ev * 100:.1f}%)")
    print("\nexception types:")
    for c, n in codes.most_common():
        print(f"  {c:24} {n:6}  ({n / max(stats['exception'], 1) * 100:.1f}%)")

    if args.sample and rows_out:
        random.seed(args.seed)
        picked = random.sample(rows_out, min(args.sample, len(rows_out)))
        blind = Path(args.blind)
        with blind.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["doc_id", "vendor_key", "what_the_system_flagged",
                        "genuine_exception? (y/n)", "labeller", "notes"])
            for r in picked:
                w.writerow([r["doc_id"], r["vendor_key"],
                            "; ".join(f"{f['code']}: {f['detail']}" for f in r["findings"]),
                            "", "", ""])
        print(f"\nwrote {len(picked)} rows for blind labelling -> {blind}")
        print("Both of you fill the y/n column independently, without discussing.")


if __name__ == "__main__":
    main()
