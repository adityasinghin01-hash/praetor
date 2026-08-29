"""What Rule 4 would cost, measured against the published run, with no model calls.

`FINDINGS.md` §6 reports 65 exceptions reduced to 47 human touches — 28% fewer, precision
1.000 — measured with Rule 4 OFF. Turning it on changes outcomes, so shipping it without
re-measuring would leave a published number describing a system that no longer runs. The
re-measurement needs ~65 hosted calls, and the free tier is 20 per day (§4).

It does not need them. **The agent's vote is the only part of an adjudication that costs
money**, and every vote from that run is stored in `results/adjudication.jsonl`. Everything
else -- the findings, the supplier pattern, the context spans, the amount -- is rebuilt
from the frozen corpus by the same functions `eval/run_adjudication.py` uses, and the
post-agent gate is `praetor.agents.exception_agent.gate_decision`, imported rather than
copied.

So this replays the stored votes through the real gate, twice.

**The check that makes the answer trustworthy** runs first: replayed with Rule 4 off, every
decision must come back byte-identical to the one the hosted run recorded. If it does not,
the replay is not reconstructing the published run and its Rule 4 number means nothing. It
is asserted, not eyeballed.

    python eval/replay_rule4.py
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.build_vendor_master import MIN_INVOICES, pattern_from, vendor_key  # noqa: E402
from eval.run_adjudication import context_spans  # noqa: E402
from praetor.agents.exception_agent import gate_decision  # noqa: E402
from praetor.baseline_rules import evaluate  # noqa: E402
from praetor.docile_adapter import load_annotation, to_record  # noqa: E402
from praetor.types import Verdict  # noqa: E402
import re  # noqa: E402


def _amount(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", value.replace(",", "")))
    except ValueError:
        return None


def flagged_exceptions(annotations: Path, master: Path):
    """Exactly what eval/run_adjudication.py flags, rebuilt from the frozen corpus."""
    obs = json.loads(master.read_text())
    out = []
    for p in sorted(annotations.glob("*.json")):
        ann, doc_hash = load_annotation(p)
        rec = to_record(ann, doc_hash, doc_id=p.stem)
        vk = vendor_key(rec.get("vendor_name"))
        rows = obs.get(vk, [])
        if len(rows) < MIN_INVOICES + 1:
            continue
        pattern = pattern_from(vk, rows, exclude_doc=rec.doc_id)
        d = evaluate(rec, pattern)
        if d.verdict is Verdict.EXCEPTION:
            out.append({"doc_id": rec.doc_id, "findings": d.findings, "pattern": pattern,
                        "context": context_spans(ann), "record": rec,
                        "amount": _amount(rec.get("amount_total"))})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--master", default="out/vm_constructed.json")
    ap.add_argument("--votes", default="results/adjudication.jsonl")
    ap.add_argument("--out", default="out/rule4_replay.json")
    args = ap.parse_args()

    votes = {}
    for line in Path(args.votes).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            votes[r["doc_id"]] = r

    cases = [c for c in flagged_exceptions(Path(args.annotations), Path(args.master))
             if c["doc_id"] in votes]
    if not cases:
        sys.exit("no stored votes match the rebuilt exceptions")

    # ---- 1. the check. Rule 4 off must reproduce the published run exactly.
    mismatches = []
    for c in cases:
        stored = votes[c["doc_id"]]
        final, _ovr, _why = gate_decision(
            stored["agent_decision"], c["findings"], c["pattern"], c["context"],
            register=None, invoice_amount=c["amount"], record=None, require_rule=False)
        if final != stored["decision"]:
            mismatches.append((c["doc_id"], stored["decision"], final))
    if mismatches:
        print("REPLAY DOES NOT REPRODUCE THE PUBLISHED RUN -- the Rule 4 number below "
              "would be meaningless. Mismatches:")
        for d, was, now in mismatches[:10]:
            print(f"  {d}: published {was}, replayed {now}")
        sys.exit(1)
    print(f"replay reproduces the published run exactly on all {len(cases)} exceptions\n")

    # ---- 2. the measurement, in the two configurations that differ.
    #
    # The published harness passes neither the record nor the PO register. R1 reads the
    # register and R4 reads the record, so run that way they cannot fire at all -- Rule 4
    # would be strictly "refuse every resolve" and the number would describe a harness
    # rather than the rule. Both are reported.
    # `register=None` is not "no register": praetor/authority.py falls back to
    # DEFAULT_REGISTER, which is data/po_register.json -- the register generated for this
    # corpus, and the one FINDINGS §8's table is measured against. Passing
    # out/po_register.json here was wrong twice over: the wrong shape (it is raw JSON,
    # not a loaded register) and the wrong corpus (29 orders belonging to a different
    # generation). Left as None, so the real one loads.
    #
    # `record` is the difference that matters. eval/run_adjudication.py passes none, so
    # R4 -- "the flagged field matches this client's record for the supplier" -- reads an
    # empty record and can never fire. Rule 4 shipped through that harness would be
    # missing a quarter of its own rule set.
    results = {}
    for label, rec_arg in (
            ("as eval/run_adjudication.py calls it -- no record, so R4 cannot fire", False),
            ("with the invoice record supplied, so all four rules can fire", True)):
        counts: Counter = Counter()
        flipped = []
        for c in cases:
            stored = votes[c["doc_id"]]
            final, ovr, why = gate_decision(
                stored["agent_decision"], c["findings"], c["pattern"], c["context"],
                register=None, invoice_amount=c["amount"],
                record=c["record"] if rec_arg else None, require_rule=True)
            counts[final] += 1
            if final != stored["decision"]:
                flipped.append({"doc_id": c["doc_id"], "was": stored["decision"],
                                "now": final, "why": why,
                                "codes": [f.code for f in c["findings"]]})
        results[label] = {"counts": dict(counts), "flipped": flipped}

    total = len(cases)
    published_resolved = sum(1 for c in cases if votes[c["doc_id"]]["decision"] == "resolve")
    published_touches = total - published_resolved

    print(f"PUBLISHED (FINDINGS §6, Rule 4 off)")
    print(f"  {total} exceptions -> {published_touches} human touches   "
          f"({published_resolved} resolved, {published_resolved / total:.1%} autonomy)\n")

    for label, r in results.items():
        resolved = r["counts"].get("resolve", 0)
        touches = total - resolved
        print(f"WITH RULE 4 ON, {label}")
        print(f"  {total} exceptions -> {touches} human touches   "
              f"({resolved} resolved, {resolved / total:.1%} autonomy)")
        print(f"  {len(r['flipped'])} resolves became escalations")
        for f in r["flipped"][:6]:
            print(f"    {f['doc_id']}  {','.join(f['codes'])}  ->  {f['why']}")
        print()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"exceptions": total, "published_resolved": published_resolved,
         "published_touches": published_touches,
         "rule4": {k: {"counts": v["counts"], "flipped": v["flipped"]}
                   for k, v in results.items()}}, indent=1) + "\n")
    print(f"-> {args.out}")
    print("\nNo model was called. The agent's votes are replayed from "
          f"{args.votes}.")


if __name__ == "__main__":
    main()
