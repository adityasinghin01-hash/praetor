"""Fetch SROIE and write it in DocILE's annotation shape.

Why: DocILE requires a human-approved access request with no stated turnaround, and
we cannot afford to discover on day 4 that it never arrived. SROIE needs no approval
and is structurally the same — real scanned documents, annotated fields, word-level
bounding boxes.

By emitting DocILE-shaped files, every downstream script works unchanged and swapping
to the real DocILE corpus later is a path change rather than a rewrite.

Verified 25 Aug on a 600-row sample: 221 distinct companies, 35 with >=3 receipts,
covering 63% of documents — enough to learn genuine per-vendor patterns.

Usage:
    python eval/fetch_sroie.py --out data/sroie_annotations --limit 1000
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

BASE = ("https://datasets-server.huggingface.co/rows"
        "?dataset=jsdnrs%2FICDAR2019-SROIE&config=default&split=train")

# SROIE entity key -> DocILE-style fieldtype (matches praetor/docile_adapter.FIELD_MAP)
ENTITY_MAP = {
    "company": "vendor_name",
    "address": "vendor_address",
    "total": "amount_total",
    "date": "invoice_date",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def locate(value: str, words: list[str], bboxes: list[list[int]]) -> list[int] | None:
    """Find the bbox covering `value` by matching a contiguous run of words."""
    target = _norm(value)
    if not target:
        return None
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(i + 12, len(words))):
            acc += _norm(words[j])
            if acc == target or (len(acc) > 6 and target.startswith(acc) and j - i > 0
                                 and _norm("".join(words[i:j + 1])) == target):
                boxes = bboxes[i:j + 1]
                return [min(b[0] for b in boxes), min(b[1] for b in boxes),
                        max(b[2] for b in boxes), max(b[3] for b in boxes)]
            if len(acc) > len(target):
                break
    # fall back: single word containing the value
    for w, b in zip(words, bboxes):
        if target and target in _norm(w):
            return b
    return None


def to_docile_shape(row: dict) -> dict | None:
    words = row.get("words") or []
    bboxes = row.get("bboxes") or []
    size = row.get("image_size") or {}
    W, H = size.get("width") or 1, size.get("height") or 1
    if not words or len(words) != len(bboxes):
        return None

    fields = []
    for ent_key, ftype in ENTITY_MAP.items():
        val = (row.get("entities") or {}).get(ent_key)
        if not val:
            continue
        box = locate(str(val), words, bboxes)
        if box is None:
            continue
        fields.append({
            "fieldtype": ftype,
            "text": str(val).strip(),
            "page": 0,
            "bbox": [box[0] / W, box[1] / H, box[2] / W, box[3] / H],
            "line_item_id": None,
        })

    # every word is also a span, so the reader sees the whole document
    for w, b in zip(words, bboxes):
        fields.append({
            "fieldtype": "other",
            "text": str(w).strip(),
            "page": 0,
            "bbox": [b[0] / W, b[1] / H, b[2] / W, b[3] / H],
            "line_item_id": None,
        })

    return {"field_extractions": fields, "source": "sroie"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sroie_annotations")
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for off in range(0, args.limit, 100):
        url = f"{BASE}&offset={off}&length=100"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.load(r)
        except Exception as e:  # noqa: BLE001
            print(f"fetch failed at offset {off}: {str(e)[:100]}")
            break
        rows = data.get("rows", [])
        if not rows:
            break
        for row in rows:
            rec = row["row"]
            shaped = to_docile_shape(rec)
            if shaped is None:
                skipped += 1
                continue
            key = rec.get("key") or f"doc{off}_{written}"
            (out / f"{key}.json").write_text(json.dumps(shaped))
            written += 1
        print(f"  {written} written, {skipped} skipped", flush=True)

    print(f"\nwrote {written} annotation files to {out}")
    print(f"skipped {skipped} (missing or misaligned words/bboxes)")


if __name__ == "__main__":
    main()
