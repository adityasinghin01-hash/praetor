"""The real path, end to end: model reads spans, resolver checks them, rules decide.

Why this exists. Every other script builds an InvoiceRecord with `to_record()`, straight
from the annotations -- correct, but it skips the two components the architecture is
actually about. The quarantined reader and the resolver were exercised only by tests, so
the headline guarantee ("the model handles references, never values") was enforced in
CI and bypassed in the running system. A diagram whose first two boxes never execute is
a diagram making a claim it does not keep.

This runs the path for real:

    document -> spans -> quarantined reader -> resolver -> rules

and reports two things:

  * EXTRACTION ACCURACY -- what the model got right, measured against the annotations,
    which is the metric the spec asked for and nothing produced;
  * REJECTIONS -- how often the model answered with a literal value or a span that does
    not exist, and was refused. This is the guarantee doing its job, counted.

Runs on the local Gemma by default: no API key, no quota, no cost, so the path that
carries the security claim is the one anybody can re-run.

    python eval/run_readpath.py --limit 25
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praetor.agents import local_reader, reader as remote_reader  # noqa: E402
from praetor import canary  # noqa: E402
from praetor.docile_adapter import (load_annotation, span_kinds_of,  # noqa: E402
                                    spans_of, to_record)
from praetor.resolver import resolve  # noqa: E402

FIELDS = ("vendor_name", "invoice_number", "amount_total",
          "currency", "bank_account", "tax_rate", "vendor_address")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--model", default=local_reader.DEFAULT_MODEL)
    ap.add_argument("--remote", action="store_true",
                    help="use the hosted Gemini reader instead of local Gemma. Costs "
                         "one call per document and is capped by praetor/costguard.py.")
    ap.add_argument("--out", default="out/readpath.jsonl")
    args = ap.parse_args()

    if args.remote:
        label = "/".join(remote_reader.MODEL_CHAIN)

        def read_spans(spans):
            return remote_reader.read(spans).mapping
    else:
        if not local_reader.available(args.model):
            sys.exit(f"{args.model} is not available. Start Ollama and pull it:\n"
                     f"  ollama serve &\n  ollama pull {args.model}")
        label = args.model

        def read_spans(spans):
            return local_reader.read(spans, model=args.model).mapping

    docs = sorted(Path(args.annotations).glob("*.json"))[: args.limit]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    per_field = {f: Counter() for f in FIELDS}
    rejections: Counter = Counter()
    rejection_examples: list[str] = []
    canary_fired: Counter = Counter()
    canary_examples: list[str] = []
    started = time.time()

    print(f"running {len(docs)} documents through the real path on {label}\n")

    with out_path.open("w") as fh:
        for i, p in enumerate(docs, 1):
            ann, doc_hash = load_annotation(p)
            spans = spans_of(ann, doc_hash)
            truth = to_record(ann, doc_hash, doc_id=p.stem)

            mapping = read_spans(spans)
            res = resolve(mapping, spans, doc_hash, p.stem)
            # The canary runs on the live path, not only in tests. It reads the span's
            # LABEL, never its text, so nothing an attacker writes is an input to it.
            canaries = canary.check(res.record, span_kinds_of(ann))
            for c in canaries:
                canary_fired[c.code] += 1
                if len(canary_examples) < 6:
                    canary_examples.append(f"{p.stem}  {c.detail}")

            row = {"doc_id": p.stem, "rejected": res.rejected,
                   "canary": [c.code for c in canaries], "fields": {}}
            for f in FIELDS:
                expected = truth.get(f)
                got = res.record.get(f)
                if expected is None and got is None:
                    outcome = "absent"
                elif got is None:
                    outcome = "missed"
                elif expected is None:
                    outcome = "spurious"
                elif got.strip() == expected.strip():
                    outcome = "correct"
                else:
                    outcome = "wrong"
                per_field[f][outcome] += 1
                row["fields"][f] = outcome

            for attr, why in res.rejected.items():
                kind = ("literal value" if "not a span reference" in why
                        else "unknown span" if "not present" in why else "other")
                rejections[kind] += 1
                if len(rejection_examples) < 6:
                    rejection_examples.append(f"{p.stem}  {attr}: {why}")

            fh.write(json.dumps(row) + "\n")
            mark = f"  {len(res.rejected)} rejected" if res.rejected else ""
            print(f"  [{i:>3}/{len(docs)}] {p.stem}{mark}", flush=True)

    elapsed = time.time() - started

    # ---- extraction accuracy, the metric the spec asked for
    tp = sum(c["correct"] for c in per_field.values())
    wrong = sum(c["wrong"] for c in per_field.values())
    missed = sum(c["missed"] for c in per_field.values())
    spurious = sum(c["spurious"] for c in per_field.values())
    retrieved = tp + wrong + spurious
    relevant = tp + wrong + missed
    precision = tp / retrieved if retrieved else 0.0
    recall = tp / relevant if relevant else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print("\n" + "=" * 66)
    print(f"EXTRACTION ACCURACY  ({len(docs)} documents, model {label})")
    print(f"  correct            {tp}")
    print(f"  wrong field        {wrong}")
    print(f"  missed             {missed}")
    print(f"  spurious           {spurious}")
    print(f"\n  precision {precision:.3f}   recall {recall:.3f}   F1 {f1:.3f}")

    print("\n  by field:")
    print(f"    {'field':<18}{'correct':>8}{'wrong':>7}{'missed':>8}{'absent':>8}")
    for f in FIELDS:
        c = per_field[f]
        print(f"    {f:<18}{c['correct']:>8}{c['wrong']:>7}{c['missed']:>8}{c['absent']:>8}")

    # ---- the guarantee, counted
    total_rejected = sum(rejections.values())
    print(f"\nREJECTIONS BY THE RESOLVER   {total_rejected}")
    print("  (the model answered with something that was not a usable reference,")
    print("   and the value never reached the record)")
    for kind, n in rejections.most_common():
        print(f"    {kind:<18} {n}")
    for ex in rejection_examples:
        print(f"    {ex[:96]}")
    if not total_rejected:
        print("    none on this sample")

    # ---- the canary, counted. Fires on origin, never on wording.
    total_canary = sum(canary_fired.values())
    print(f"\nCANARY FIRINGS   {total_canary}")
    print("  (a guarded field arrived from a span the document does not label as a")
    print("   place that field can legitimately come from -- checked without reading it)")
    for code, n in canary_fired.most_common():
        print(f"    {code:<18} {n}")
    for ex in canary_examples:
        print(f"    {ex[:96]}")
    if not total_canary:
        print("    none on this sample -- no guarded field came from an impossible place")

    print(f"\nthroughput: {len(docs) / elapsed:.2f} documents/second "
          f"({elapsed:.1f}s total, local, single machine)")
    if args.remote:
        from praetor import costguard
        print(f"cost: {costguard.report()}")
    else:
        print(f"cost: Rs 0 -- {label} runs on this machine")
    print(f"\nper-document detail -> {out_path}")


if __name__ == "__main__":
    main()
