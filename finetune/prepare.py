"""Build the fine-tuning corpus for the quarantined reader, held out by layout.

The task is the production task and nothing else: the model is shown a document's
spans and must answer with span ids. The prompt is imported from
`praetor.agents.reader.PROMPT` rather than copied, so a fine-tune can never drift
from the prompt the shipped reader sends -- if that prompt changes, this data is
rebuilt from the new one or it is not rebuilt at all.

Two disciplines, both taken from mistakes this repo already made:

**Held out by layout, not by document.** `FINDINGS.md` §17: held out by document,
a component memorises five page templates and looks strong. The test set here is
every document of one layout the fit never saw.

**The span listing is shuffled.** Measured before any training: `payment_iban` is
the fifth span in 342 of 342 annotations. A model trained on the natural order can
score perfectly by answering "the fifth line" and reading nothing, which is exactly
the shortcut that inflated the weak reader's F1 to 0.384 in §10. The shuffle is
deterministic per document, so the corpus is reproducible bit for bit, and
`--order natural` exists so the difference can be measured rather than assumed.

    python finetune/prepare.py --holdout letterhead
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praetor.agents.reader import PROMPT, WANTED_FIELDS  # noqa: E402
from praetor.docile_adapter import (FIELD_MAP, _span_id, load_annotation,  # noqa: E402
                                    spans_of)

LAYOUTS = ("banded", "classic", "compact", "letterhead", "remit_right")


def truth_mapping(ann: dict) -> dict[str, str | None]:
    """field -> the span id that actually holds it. First occurrence wins, exactly
    as `docile_adapter.to_record` decides it, so the target of the fine-tune is the
    same answer the resolver would accept."""
    out: dict[str, str | None] = {f: None for f in WANTED_FIELDS}
    for fld in ann.get("field_extractions", []):
        attr = FIELD_MAP.get(fld.get("fieldtype"))
        if attr and out.get(attr) is None:
            out[attr] = _span_id(int(fld.get("page", 0)), fld.get("bbox", [0, 0, 0, 0]))
    return out


def listing(spans: dict[str, str], doc_id: str, order: str) -> str:
    items = list(spans.items())
    if order == "shuffled":
        random.Random(f"spanorder:{doc_id}").shuffle(items)
    return "\n".join(f"{sid}\t{text}" for sid, text in items)


def example(path: Path, order: str) -> dict:
    ann, doc_hash = load_annotation(path)
    spans = spans_of(ann, doc_hash)
    prompt = PROMPT.format(fields=", ".join(WANTED_FIELDS),
                           spans=listing(spans, path.stem, order))
    # separators: the completion is what the model must reproduce character for
    # character, so it is written the one way json.dumps writes it by default.
    return {"prompt": prompt, "completion": json.dumps(truth_mapping(ann)),
            "layout": ann.get("layout", "unknown"), "doc_id": path.stem}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--holdout", default="letterhead", choices=LAYOUTS)
    ap.add_argument("--order", default="shuffled", choices=("shuffled", "natural"))
    ap.add_argument("--valid", type=int, default=30,
                    help="documents held back from the TRAINING layouts for validation. "
                         "Never from the held-out layout: selecting on the test layout "
                         "is how a layout hold-out gets quietly undone.")
    ap.add_argument("--out", default="finetune/data")
    args = ap.parse_args()

    docs = sorted(Path(args.annotations).glob("*.json"))
    if not docs:
        sys.exit(f"no annotations under {args.annotations}")

    train, test = [], []
    for p in docs:
        ex = example(p, args.order)
        (test if ex["layout"] == args.holdout else train).append(ex)

    if not test:
        sys.exit(f"no documents with layout {args.holdout!r}")

    random.Random(f"split:{args.holdout}").shuffle(train)
    valid, train = train[: args.valid], train[args.valid:]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("valid", valid), ("test", test)):
        with (out / f"{name}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    meta = {"holdout": args.holdout, "order": args.order,
            "train": len(train), "valid": len(valid), "test": len(test),
            "train_layouts": sorted({r["layout"] for r in train}),
            "prompt_sha": __import__("hashlib").sha256(PROMPT.encode()).hexdigest()[:16]}
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")

    print(f"holdout layout : {args.holdout}   span order: {args.order}")
    print(f"train {len(train)}   valid {len(valid)}   test {len(test)}   -> {out}")
    print(f"train layouts  : {', '.join(meta['train_layouts'])}")
    print(f"prompt sha256  : {meta['prompt_sha']}  (praetor.agents.reader.PROMPT)")


if __name__ == "__main__":
    main()
