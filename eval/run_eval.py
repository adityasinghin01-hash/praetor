"""Score a detector against ground truth.

Right now it scores the RULES BASELINE. The agent slots in beside it with the same
scoring, so the comparison is like-for-like — that is the whole point of having
written the baseline first.

Ground truth only exists for the constructed corpus, where each deviation was
introduced deliberately and is therefore known exactly.

Usage:
    python eval/run_eval.py --truth data/constructed_truth.jsonl \
        --predictions out/exc_constructed.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

# deviation we introduced -> finding code the detector should raise
# A deviation can have more than one correct explanation, so these are sets.
#
# `AMOUNT_SPIKE` is the case that forced it. On a corpus with line items, inflating the
# total also stops the lines adding up, and "the items do not add up to the total" is a
# more precise account of what is wrong than "bigger than this supplier's usual". Scoring
# only the second would mark the better answer wrong.
EXPECTED: dict[str, frozenset[str]] = {
    "BANK_ACCOUNT_CHANGED": frozenset({"BANK_UNKNOWN"}),
    "CURRENCY_CHANGED": frozenset({"CURRENCY_MISMATCH"}),
    "TAX_RATE_CHANGED": frozenset({"TAX_RATE_MISMATCH"}),
    "ADDRESS_CHANGED": frozenset({"ADDRESS_MISMATCH"}),
    "AMOUNT_SPIKE": frozenset({"AMOUNT_OUT_OF_RANGE", "LINE_ITEMS_DO_NOT_SUM"}),
    "DUPLICATE_INVOICE_NUMBER": frozenset({"DUPLICATE_INVOICE"}),
    "MISSING_BANK_ACCOUNT": frozenset({"MISSING_FIELD"}),
    "LINE_ITEMS_MISMATCH": frozenset({"LINE_ITEMS_DO_NOT_SUM"}),
}


def _reason_right(dev: str | None, codes) -> bool:
    return bool(dev) and bool(EXPECTED.get(dev, frozenset()) & set(codes))


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--label", default="rules baseline")
    args = ap.parse_args()

    truth = {}
    for line in Path(args.truth).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            truth[r["doc_id"]] = r.get("deviation")

    pred: dict[str, list[str]] = {}
    for line in Path(args.predictions).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            pred[r["doc_id"]] = r.get("codes", [])

    # --- document level: did we flag the right documents at all? ---
    tp = fp = fn = tn = 0
    for doc_id, dev in truth.items():
        flagged = doc_id in pred
        if dev and flagged:
            tp += 1
        elif dev and not flagged:
            fn += 1
        elif not dev and flagged:
            fp += 1
        else:
            tn += 1

    p, r, f = prf(tp, fp, fn)
    n = len(truth)
    print(f"=== {args.label} — document level ({n} documents) ===")
    print(f"  planted deviations : {tp + fn}")
    print(f"  flagged            : {tp + fp}")
    print(f"  true positives     : {tp}")
    print(f"  false positives    : {fp}")
    print(f"  false negatives    : {fn}")
    print(f"\n  precision {p:.3f}   recall {r:.3f}   F1 {f:.3f}")

    # --- reason level: did we flag it for the RIGHT reason? ---
    right = sum(1 for d, dev in truth.items()
                if dev and d in pred and _reason_right(dev, pred[d]))
    caught = tp or 1
    print(f"\n  correct reason     : {right}/{tp}  ({right / caught * 100:.0f}% of catches)")

    # --- per deviation type ---
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "hit": 0, "reason": 0})
    for doc_id, dev in truth.items():
        if not dev:
            continue
        per[dev]["n"] += 1
        if doc_id in pred:
            per[dev]["hit"] += 1
            if _reason_right(dev, pred[doc_id]):
                per[dev]["reason"] += 1

    print(f"\n{'deviation':28} {'n':>4} {'found':>6} {'right reason':>13}")
    for dev, s in sorted(per.items()):
        print(f"  {dev:26} {s['n']:4} {s['hit']:6} {s['reason']:13}")

    if fp:
        extra: dict[str, int] = defaultdict(int)
        for doc_id, codes in pred.items():
            if not truth.get(doc_id):
                for c in codes:
                    extra[c] += 1
        print("\nfalse-positive reasons:")
        for c, k in sorted(extra.items(), key=lambda kv: -kv[1]):
            print(f"  {c:26} {k}")


if __name__ == "__main__":
    main()
