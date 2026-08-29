"""Run an on-device model through the real path and score it the way §10 scores it.

    document -> spans -> quarantined reader -> resolver -> canary

Same prompt as production (imported, never copied), same scorer as
`eval/run_readpath.py` (`eval/readscore.py`), so the base model, the fine-tune, the
Ollama reader and the hosted reader all produce numbers that can be put in one table.

Two things are reported that an accuracy number alone would hide:

  * **rejections** -- how often the model answered with a literal value or an id that is
    not a real span, and `praetor/resolver.py` refused it. Accuracy is a property of the
    model. This is a property of the architecture.
  * **`bank_account` specifically** -- the privileged field, the only one a deployment
    would have to depend on.

`--order` decides how the spans are listed. `payment_iban` is the fifth span in 342 of
342 annotations, so `natural` lets a model answer "the fifth line" and read nothing.
Both orders are measured; the gap between them is how much of a score is the shortcut.

Runs under the arm64 venv that has mlx (see finetune/README.md). `praetor/` is standard
library only, which is why it imports there at all.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.readscore import FIELDS, outcome, render, score_rows  # noqa: E402
from finetune.prepare import listing, truth_mapping  # noqa: E402
from praetor import canary  # noqa: E402
from praetor.agents.reader import PROMPT, WANTED_FIELDS, _parse  # noqa: E402
from praetor.docile_adapter import load_annotation, span_kinds_of, spans_of  # noqa: E402
from praetor.resolver import resolve  # noqa: E402

BASE_MODEL = "mlx-community/gemma-3-1b-it-4bit"


def build_reader(model_path: str, adapter: str | None, max_tokens: int):
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(model_path, adapter_path=adapter)
    sampler = make_sampler(temp=0.0)   # greedy: the same document must give the same span

    def run(prompt: str) -> str:
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], add_generation_prompt=True,
            tokenize=False)
        return generate(model, tokenizer, prompt=text, max_tokens=max_tokens,
                        sampler=sampler, verbose=False)

    label = Path(model_path).name + (f" + {Path(adapter).name}" if adapter else " (base)")
    return run, label


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--layout", default="",
                    help="score documents of this layout instead of the split file. "
                         "Use a TRAINING layout to separate 'the model cannot do the "
                         "task' from 'the model cannot do it on an unseen page template'.")
    ap.add_argument("--split", default="finetune/data/test.jsonl",
                    help="which documents to score. Defaults to the held-out layout "
                         "written by finetune/prepare.py.")
    ap.add_argument("--model", default=BASE_MODEL)
    ap.add_argument("--adapter", default=None, help="path to LoRA adapters")
    ap.add_argument("--order", default="shuffled", choices=("shuffled", "natural"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=260)
    ap.add_argument("--out", default="out/finetune_eval.jsonl")
    args = ap.parse_args()

    if args.layout:
        doc_ids = [p.stem for p in sorted(Path(args.annotations).glob("*.json"))
                   if json.loads(p.read_text()).get("layout") == args.layout]
    else:
        doc_ids = [json.loads(l)["doc_id"] for l in Path(args.split).read_text().splitlines()
                   if l.strip()]
    if args.limit:
        doc_ids = doc_ids[: args.limit]
    ann_dir = Path(args.annotations)

    run, label = build_reader(args.model, args.adapter, args.max_tokens)
    label = f"{label}, {args.order} order"

    rejections: Counter = Counter()
    rejection_examples: list[str] = []
    canary_fired: Counter = Counter()
    rows: list[dict] = []
    started = time.time()
    print(f"scoring {len(doc_ids)} documents on {label}\n", flush=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for i, doc_id in enumerate(doc_ids, 1):
            ann, doc_hash = load_annotation(ann_dir / f"{doc_id}.json")
            spans = spans_of(ann, doc_hash)
            truth = truth_mapping(ann)
            prompt = PROMPT.format(fields=", ".join(WANTED_FIELDS),
                                   spans=listing(spans, doc_id, args.order))

            raw = run(prompt)
            mapping = _parse(raw)
            res = resolve(mapping, spans, doc_hash, doc_id)
            fired = [c.code for c in canary.check(res.record, span_kinds_of(ann))]
            for c in fired:
                canary_fired[c] += 1

            # The raw reply is stored, not just the parsed mapping. FINDINGS §7 exists
            # because somebody looked at one: the failure a score hides is what the
            # model actually wrote.
            row = {"doc_id": doc_id, "rejected": res.rejected, "canary": fired,
                   "raw": raw[:600], "mapping": mapping, "truth": truth, "fields": {}}
            for f in FIELDS:
                # The record holds resolved TEXT; the truth here is a span id. Compare
                # like with like: what the model pointed at, versus what it should have.
                got = mapping.get(f)
                got = got if got in spans else None
                row["fields"][f] = outcome(truth.get(f), got)
            rows.append(row)

            for attr, why in res.rejected.items():
                kind = ("literal value" if "not a span reference" in why
                        else "unknown span" if "not present" in why else "other")
                rejections[kind] += 1
                if len(rejection_examples) < 6:
                    rejection_examples.append(f"{doc_id}  {attr}: {why}")

            fh.write(json.dumps(row) + "\n")
            mark = f"  {len(res.rejected)} rejected" if res.rejected else ""
            print(f"  [{i:>3}/{len(doc_ids)}] {doc_id}{mark}", flush=True)

    elapsed = time.time() - started
    s = score_rows(rows)
    print("\n" + render(s, label, len(rows)))

    total_rejected = sum(rejections.values())
    print(f"\nREJECTIONS BY THE RESOLVER   {total_rejected}")
    for kind, n in rejections.most_common():
        print(f"    {kind:<18} {n}")
    for ex in rejection_examples:
        print(f"    {ex[:96]}")
    if not total_rejected:
        print("    none on this sample")

    bank = s.per_field["bank_account"]
    print(f"\nTHE PRIVILEGED FIELD   bank_account")
    print(f"    correct {bank['correct']}   wrong {bank['wrong']}   "
          f"never returned {bank['missed']}   of {len(rows)}")

    print(f"\nCANARY FIRINGS   {sum(canary_fired.values())}")
    for code, n in canary_fired.most_common():
        print(f"    {code:<18} {n}")

    print(f"\nthroughput: {len(rows) / elapsed:.2f} documents/second "
          f"({elapsed:.1f}s total, on-device)")
    print(f"cost: Rs 0 -- this model runs on this machine")
    print(f"\nper-document detail -> {out_path}")


if __name__ == "__main__":
    main()
