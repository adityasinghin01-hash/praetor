"""The undefended baseline: one prompt, the whole document as text, a value back.

This is the system every published injection number is measured against, and it is what
VSB exists to compare a defence to. The instruction is `eval/measure_attacks.py::SYSTEM`
verbatim -- the same prompt FINDINGS §1 used to measure 12 of 20 -- imported rather than
copied, so the baseline cannot quietly become a strawman.

It reads `document.text`, not the spans: a system with no span contract is exactly what
this represents.

    python benchmark/run_naive.py --reader ollama --tier core
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import readers  # noqa: E402
from eval.measure_attacks import SYSTEM  # noqa: E402


def parse(raw: str) -> tuple[str | None, bool]:
    """(value, escalated). The prompt offers `action: pay|hold`, so a hold is the
    undefended system's own way of sending a document to a person, and it is scored as
    an escalation rather than as a miss."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None, False
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, False
    value = obj.get("bank_account")
    value = None if value in (None, "", "null") else str(value)
    return value, str(obj.get("action", "")).lower() == "hold"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="benchmark/data/vsb.jsonl")
    ap.add_argument("--reader", default="ollama",
                    choices=("ollama", "mlx", "gemini"))
    ap.add_argument("--model", default="")
    ap.add_argument("--adapter", default="")
    ap.add_argument("--tier", default="all", choices=("all", "core"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="out/vsb_naive.jsonl")
    args = ap.parse_args()

    cases = [json.loads(l) for l in Path(args.cases).read_text().splitlines() if l.strip()]
    if args.tier == "core":
        cases = [c for c in cases if c.get("tier") == "core"]
    if args.limit:
        cases = cases[: args.limit]

    run, label = readers.build(args.reader, args.model, args.adapter)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resumable: a free-tier 429 should cost one case, not the run.
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["case_id"])

    started = time.time()
    print(f"naive baseline on {label}: {len(cases)} cases "
          f"({len(done)} already done)\n", flush=True)
    with out_path.open("a") as fh:
        for i, c in enumerate(cases, 1):
            if c["case_id"] in done:
                continue
            prompt = (f"{SYSTEM}\n\n--- DOCUMENT ---\n{c['document']['text']}\n--- END ---")
            raw = run(prompt)
            value, escalated = parse(raw)
            fh.write(json.dumps({"case_id": c["case_id"], "value": value,
                                 "escalated": escalated, "system": f"naive/{label}"}) + "\n")
            fh.flush()
            print(f"  [{i:>4}/{len(cases)}] {c['case_id']:<40} "
                  f"{'HOLD' if escalated else (value or '-')}", flush=True)

    print(f"\n{len(cases)} cases in {time.time() - started:.0f}s -> {out_path}")
    print(f"score it:  python benchmark/score.py --predictions {out_path} "
          f"--system 'naive/{label}'")


if __name__ == "__main__":
    main()
