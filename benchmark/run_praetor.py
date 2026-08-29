"""PRAETOR as a VSB reference system: the extraction defences, end to end.

    spans -> quarantined reader -> resolver -> canary
                                -> path B (shape and composition) -> corroboration

**Scope, stated rather than implied.** This runs the defences that decide whether a
value may leave the document. It does NOT run the rules layer or the gate, because those
compare against a vendor master and VSB cases have no vendor history -- every case would
escalate as a first-time supplier (FINDINGS §20 records exactly that happening in the
cloud) and the benchmark would measure nothing about extraction. The number here is what
the extraction path does on its own, and the rules layer only ever escalates further.

A case is escalated when any of these hold, which is what the product does:

  * the resolver refused the answer, or the reader named no span
  * the canary fired -- the value arrived from a span the document does not label as a
    place a payable account can come from
  * the two paths disagreed, or Path B abstained

Path B is always scored by the fold that did NOT see the case's layout.

    python benchmark/run_praetor.py --reader mlx --adapter finetune/adapters/letterhead
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import readers  # noqa: E402
from praetor import canary, corroboration  # noqa: E402
from praetor.agents.reader import PROMPT, WANTED_FIELDS, _parse  # noqa: E402
from praetor.pathb import extract as path_b_extract  # noqa: E402
from praetor.resolver import resolve  # noqa: E402

TARGET = "bank_account"

# Two readers that call no model, so VSB can be run against this architecture with no
# API key, no Ollama and no GPU -- which is what makes the reference numbers in
# FINDINGS reproducible by anybody who clones the repo.
#
#   oracle       names the span the document labels as that field: a reader that cannot
#                be wrong. Whatever still goes wrong is not the model's doing.
#   compromised  names the ATTACKER'S span for the privileged field and is correct on
#                everything else. The architecture's central claim as an experiment --
#                assume the reader is entirely lost, and measure what is left.
DETERMINISTIC = ("oracle", "compromised")


def label_mapping(kinds: dict[str, str]) -> dict[str, str]:
    from praetor.docile_adapter import FIELD_MAP
    out: dict[str, str] = {}
    for sid, label in kinds.items():
        attr = FIELD_MAP.get(label)
        if attr and attr not in out:
            out[attr] = sid
    return out


def annotation_spans(case: dict) -> list[dict]:
    """Back to the raw annotation shape Path B and the canary consume."""
    return [{"fieldtype": s["label"], "text": s["text"], "page": s["page"],
             "bbox": list(s["bbox"]), "line_item_id": None}
            for s in case["document"]["spans"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="benchmark/data/vsb.jsonl")
    ap.add_argument("--reader", default="mlx",
                    choices=("oracle", "compromised", "ollama", "mlx", "gemini"))
    ap.add_argument("--model", default="")
    ap.add_argument("--adapter", default="")
    ap.add_argument("--tier", default="all", choices=("all", "core"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-second-path", action="store_true",
                    help="reader + resolver + canary only. The ablation that says how "
                         "much of the result the second path is responsible for.")
    ap.add_argument("--out", default="out/vsb_praetor.jsonl")
    args = ap.parse_args()

    cases = [json.loads(l) for l in Path(args.cases).read_text().splitlines() if l.strip()]
    if args.tier == "core":
        cases = [c for c in cases if c.get("tier") == "core"]
    if args.limit:
        cases = cases[: args.limit]

    if args.reader in DETERMINISTIC:
        run, label = None, args.reader
    else:
        run, label = readers.build(args.reader, args.model, args.adapter)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["case_id"])

    why: Counter = Counter()
    started = time.time()
    print(f"praetor on {label}: {len(cases)} cases ({len(done)} already done)"
          f"{'  [no second path]' if args.no_second_path else ''}\n", flush=True)

    with out_path.open("a") as fh:
        for i, c in enumerate(cases, 1):
            if c["case_id"] in done:
                continue
            raw_spans = annotation_spans(c)
            spans = {s["id"]: s["text"] for s in c["document"]["spans"]}
            kinds = {s["id"]: s["label"] for s in c["document"]["spans"]}
            doc_hash = hashlib.sha256(c["document"]["text"].encode()).hexdigest()[:16]

            if args.reader in DETERMINISTIC:
                mapping = label_mapping(kinds)
                if args.reader == "compromised" and c.get("attacker"):
                    mapping["bank_account"] = c["attacker"]["span_id"]
            else:
                mapping = _parse(run(PROMPT.format(
                    fields=", ".join(WANTED_FIELDS),
                    spans="\n".join(f"{k}\t{v}" for k, v in spans.items()))))
            res = resolve(mapping, spans, doc_hash, c["case_id"])
            a_span = mapping.get(TARGET) if mapping.get(TARGET) in spans else None
            value = res.record.get(TARGET)

            reasons = []
            if TARGET in res.rejected:
                reasons.append("resolver_refused")
            if a_span is None or not value:
                reasons.append("no_span_named")
            fired = [f.code for f in canary.check(res.record, kinds)]
            if fired:
                reasons.append("canary:" + ",".join(sorted(set(fired))))

            pick = None
            if not args.no_second_path:
                pick = path_b_extract(raw_spans, layout=c["layout"])
                out = corroboration.corroborate(a_span, pick)
                if out.escalates:
                    reasons.append(f"corroboration:{out.code or 'disagree'}")

            escalated = bool(reasons)
            why[reasons[0] if reasons else "released"] += 1
            fh.write(json.dumps({
                "case_id": c["case_id"],
                "value": None if escalated else value,
                "escalated": escalated,
                "system": f"praetor/{label}",
                "reasons": reasons,
                "path_a_span": a_span,
                "path_b_span": (pick.span_id if pick else None),
                "canary": fired,
            }) + "\n")
            fh.flush()
            mark = reasons[0] if reasons else (value or "-")
            print(f"  [{i:>4}/{len(cases)}] {c['case_id']:<40} {mark}", flush=True)

    print(f"\n{len(cases)} cases in {time.time() - started:.0f}s -> {out_path}")
    print("\nwhy each case ended where it did:")
    for k, n in why.most_common():
        print(f"  {k:<34}{n:>5}")
    print(f"\nscore it:  python benchmark/score.py --predictions {out_path} "
          f"--system 'praetor/{label}'")


if __name__ == "__main__":
    main()
