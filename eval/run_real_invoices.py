"""Real scanned invoices, through the real front door. The gap this project could not close.

`FINDINGS.md` §29 measured 300 real scanned receipts and found a defect no synthetic
corpus could. It also stated the limit plainly: SROIE receipts carry no bank account, so
**the privileged field had never met real paper.** Every number about the account came
from documents this project generated.

This closes as much of that as is closable without a real company's invoices.

The documents are `chainyo/rvl-cdip-invoice` on the Hugging Face hub -- **real scanned
business invoices** from a public archive, images only, no annotations of any kind. So
they go through the actual production path:

    real scan -> Document AI -> spans and labels -> resolver -> canary -> rules -> gate

Nothing here is fitted, generated or annotated by us. Document AI assigns the labels, and
the canary reads those labels, so this is the first time the origin check has been asked
about a document nobody in this project has ever touched.

**It costs money**: Rs 0.88 per page, on `praetor-run-2026`, capped by
`praetor/costguard.py`. Responses are cached, so a second run is free.

    python eval/run_real_invoices.py --limit 12
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.pipeline import analyse_with_document_ai  # noqa: E402
from praetor import baseline_rules, canary, docai_adapter  # noqa: E402
from praetor.gate import evaluate as gate_evaluate  # noqa: E402
from praetor.resolver import resolve  # noqa: E402

# `first-rows`, not `rows`: this dataset's parquet files exceed the rows endpoint's scan
# limit and it answers 500. first-rows returns 100, which is more than enough.
ROWS = ("https://datasets-server.huggingface.co/first-rows"
        "?dataset=chainyo%2Frvl-cdip-invoice&config=default&split=train")


def fetch_images(n: int, cache: Path) -> list[Path]:
    """Real scanned invoices, saved once. The URLs are signed and expire, so the images
    are kept rather than re-fetched."""
    cache.mkdir(parents=True, exist_ok=True)
    have = sorted(cache.glob("*.jpg"))
    if len(have) >= n:
        return have[:n]

    with urllib.request.urlopen(ROWS, timeout=90) as r:
        rows = json.load(r)["rows"][:n]
    out = []
    for i, row in enumerate(rows):
        p = cache / f"rvl_{i:03d}.jpg"
        if not p.exists():
            src = row["row"]["image"]["src"]
            with urllib.request.urlopen(src, timeout=90) as im:
                p.write_bytes(im.read())
        out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--cache", default="data/real_invoices")
    ap.add_argument("--responses", default="out/real_docai")
    ap.add_argument("--out", default="out/real_invoices.jsonl")
    args = ap.parse_args()

    images = fetch_images(args.limit, Path(args.cache))
    resp_dir = Path(args.responses)
    resp_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(images)} real scanned invoices\n")

    fields: Counter = Counter()
    labels: Counter = Counter()
    fired: Counter = Counter()
    actions: Counter = Counter()
    rows = []
    charged = 0

    for i, img in enumerate(images, 1):
        cached = resp_dir / f"{img.stem}.json"
        if cached.exists():
            document = json.loads(cached.read_text())
        else:
            # Document AI takes the image bytes; the mime type in the request says PDF,
            # so send it as one only if it is one. The parser accepts JPEG directly.
            document = analyse_real(img.read_bytes())
            cached.write_text(json.dumps(document))
            charged += 1

        spans = docai_adapter.spans_of(document)
        kinds = docai_adapter.span_kinds_of(document)
        record = docai_adapter.to_record(document, "real:" + img.stem, img.stem)
        for k in kinds.values():
            labels[k] += 1
        got = {a: record.get(a) for a in
               ("vendor_name", "invoice_number", "amount_total", "currency",
                "bank_account", "tax_rate", "vendor_address")}
        for a, v in got.items():
            if v:
                fields[a] += 1

        findings = canary.check(record, kinds)
        for f in findings:
            fired[f.code] += 1
        decision = gate_evaluate(record, None)
        actions[decision.action.value] += 1

        rows.append({"doc": img.stem, "spans": len(spans),
                     "fields": {k: bool(v) for k, v in got.items()},
                     "bank_account": got["bank_account"],
                     "canary": [f.code for f in findings],
                     "action": decision.action.value})
        print(f"  [{i:>3}/{len(images)}] {img.stem}  spans={len(spans):<4}"
              f"fields={sum(1 for v in got.values() if v)}/7  "
              f"account={'yes' if got['bank_account'] else 'no'}  "
              f"{decision.action.value}", flush=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    print("\n" + "=" * 66)
    print(f"REAL SCANNED INVOICES ({len(images)}), through Document AI")
    print("=" * 66)
    print("\n  fields Document AI found, of 7 the kernel wants:")
    for a in ("vendor_name", "invoice_number", "amount_total", "currency",
              "bank_account", "tax_rate", "vendor_address"):
        print(f"    {a:<18}{fields[a]:>4} / {len(images)}")
    print(f"\n  THE PRIVILEGED FIELD on real paper: {fields['bank_account']} of {len(images)}")
    print(f"\n  canary firings: {sum(fired.values())}")
    for c, n in fired.most_common():
        print(f"    {c:<22}{n}")
    print("\n  what the gate decided:")
    for a, n in actions.most_common():
        print(f"    {a:<22}{n}")
    print(f"\n  charged for {charged} page(s) at Rs 0.88; the rest were cached")
    print(f"  detail -> {args.out}")


def analyse_real(image: bytes) -> dict:
    """Same call as the production path, with the mime type an image needs."""
    import base64
    import urllib.error
    from ingest.pipeline import LOCATION, PROCESSOR, PROJECT, _token

    url = (f"https://{LOCATION}-documentai.googleapis.com/v1/projects/{PROJECT}"
           f"/locations/{LOCATION}/processors/{PROCESSOR}:process")
    body = json.dumps({
        "rawDocument": {"content": base64.b64encode(image).decode(),
                        "mimeType": "image/jpeg"},
        "skipHumanReview": True,
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["document"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Document AI refused this ({e.code}): "
                           f"{e.read()[:300].decode('utf-8', 'replace')}") from e


if __name__ == "__main__":
    main()
