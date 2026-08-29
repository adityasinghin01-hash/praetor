"""Fetch a public prompt-injection dataset. Attacks nobody here wrote.

`FINDINGS.md` §3 concedes the sharpest criticism this project has: the 20 payloads in
`attacks/payloads.py` are hand-authored, so measuring our defence against them is marking
our own homework. The fix was always "use somebody else's attacks", and the reason it did
not happen is that no public set *matches this threat model* -- they score whether an
agent took an attacker-chosen action, and ours has no actions.

"Does not match the threat model" is not the same as "cannot be run", and §3 was careful
to call itself a structural observation rather than a measurement. This makes it possible
to run them.

Source: `deepset/prompt-injections` on the Hugging Face datasets server -- 546 rows,
labelled 1 for an injection and 0 for an ordinary question. Pulled over plain HTTPS so
this needs no `datasets` library and no token.

    python eval/fetch_public_attacks.py --out data/public_injections.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://datasets-server.huggingface.co/rows"
DATASET = "deepset/prompt-injections"


def fetch(dataset: str, split: str, batch: int = 100) -> list[dict]:
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"dataset": dataset, "config": "default",
                                    "split": split, "offset": offset, "length": batch})
        with urllib.request.urlopen(f"{ENDPOINT}?{q}", timeout=60) as r:
            payload = json.load(r)
        got = payload.get("rows", [])
        rows.extend(x["row"] for x in got)
        total = payload.get("num_rows_total", 0)
        offset += len(got)
        if not got or offset >= total:
            return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DATASET)
    ap.add_argument("--out", default="data/public_injections.jsonl")
    args = ap.parse_args()

    rows: list[dict] = []
    for split in ("train", "test"):
        try:
            rows.extend({**r, "split": split} for r in fetch(args.dataset, split))
        except Exception as e:  # noqa: BLE001
            print(f"  {split}: {e}", file=sys.stderr)

    if not rows:
        sys.exit("nothing fetched")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for i, r in enumerate(rows):
            # `payloads.load_public()` reads `text`; the rest is kept so the provenance
            # of every row is checkable without going back to the network.
            fh.write(json.dumps({"id": f"P{i:04d}", "text": r.get("text", ""),
                                 "label": r.get("label"), "split": r.get("split"),
                                 "source": args.dataset}) + "\n")

    inj = sum(1 for r in rows if r.get("label") == 1)
    print(f"{len(rows)} rows -> {out}")
    print(f"  labelled an injection : {inj}")
    print(f"  labelled ordinary     : {len(rows) - inj}")
    print(f"  source                : {args.dataset}, written by somebody else")


if __name__ == "__main__":
    main()
