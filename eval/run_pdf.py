"""The front door, end to end: a PDF goes in, a decision comes out.

    PDF -> Document AI -> spans -> quarantined reader -> resolver -> canary -> rules -> gate

This is `DECISIONS.md` #9 closed. Every other script in this repo starts from
pre-segmented annotations, which meant the honest answer to "does it work on a real
invoice?" was **no** — a PDF has no spans, so nothing downstream could run.

Nothing in the kernel changed to make this work. Document AI returns
`normalizedVertices`, which is the shape `praetor/docile_adapter.py` already consumed, so
the whole front door is one adapter and a client.

**No new dependency.** `google.auth` already ships with `google-genai`, and the call
itself is `urllib`. The kernel stays standard-library only.

    python eval/run_pdf.py out/pdf/V000_003.pdf
    python eval/run_pdf.py out/pdf/V000_003.pdf --cached   # re-use the saved response
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor import baseline_rules, canary, costguard, docai_adapter  # noqa: E402
from praetor.agents import local_reader  # noqa: E402
from praetor.gate import evaluate as gate_evaluate  # noqa: E402
from praetor.resolver import resolve  # noqa: E402

PROJECT = "praetor-run-2026"
LOCATION = "asia-south1"
PROCESSOR = "8d5e7a53f2b61215"          # praetor-invoice-parser, pretrained-invoice-v1.3

# https://cloud.google.com/document-ai/pricing — Invoice Parser, per page. There is no
# free tier, so unlike every other measurement in this repo, running this costs money.
USD_PER_PAGE = 0.01


def _token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def process(pdf: Path) -> tuple[dict, float]:
    """Send one PDF to Document AI. Returns (document, seconds)."""
    url = (f"https://{LOCATION}-documentai.googleapis.com/v1/projects/{PROJECT}"
           f"/locations/{LOCATION}/processors/{PROCESSOR}:process")
    body = json.dumps({
        "rawDocument": {"content": base64.b64encode(pdf.read_bytes()).decode(),
                        "mimeType": "application/pdf"},
        "skipHumanReview": True,
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    })
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Document AI refused this ({e.code}):\n{e.read().decode()[:600]}")
    return payload["document"], time.time() - started


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--cached", action="store_true",
                    help="re-use the saved response instead of paying for another page")
    ap.add_argument("--out", default="out/docai")
    args = ap.parse_args()

    pdf = Path(args.pdf) if Path(args.pdf).is_absolute() else ROOT / args.pdf
    if not pdf.exists():
        sys.exit(f"no such file: {pdf}")
    saved = ROOT / args.out / f"{pdf.stem}.json"

    if args.cached and saved.exists():
        document, elapsed, pages, cost = json.loads(saved.read_text()), 0.0, 0, 0.0
        print(f"using the saved response for {pdf.name} (no page charged)\n")
    else:
        document, elapsed = process(pdf)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(document))
        pages = len(document.get("pages") or [])
        cost = pages * USD_PER_PAGE
        print(f"{pdf.name} -> Document AI in {elapsed:.2f}s, {pages} page(s)\n")

    # ---- the front door: a real file becomes spans
    doc_hash = f"docai:{abs(hash(json.dumps(document, sort_keys=True))) % 16**12:012x}"
    spans = docai_adapter.spans_of(document)
    kinds = docai_adapter.span_kinds_of(document)
    reference = docai_adapter.to_record(document, doc_hash, pdf.stem)

    print(f"SPANS            {len(spans)} lines offered to the reader")
    labelled = sum(1 for k in kinds.values() if k != "other")
    print(f"  of those, {labelled} carry a field label; {len(spans) - labelled} are "
          f"ordinary text")
    unmapped = docai_adapter.unmapped_types(document)
    if unmapped:
        print(f"  entity types this adapter ignores: {sorted(unmapped)}")

    # ---- the reader, then the resolver. Unchanged from every other path.
    if not local_reader.available():
        print("\nOllama is not running, so the reader step is skipped. Start it with:")
        print("  ollama serve &  &&  ollama pull gemma3:1b")
        _report_rules(reference, kinds, doc_hash)
        return

    print("\nREADER           gemma3:1b, on this machine, no key and no quota")
    mapping = local_reader.read(spans).mapping
    res = resolve(mapping, spans, doc_hash, pdf.stem)
    print(f"  answered on     {len(mapping)} fields")
    print(f"  refused         {len(res.rejected)}")
    for attr, why in list(res.rejected.items())[:4]:
        print(f"    {attr}: {why[:64]}")

    _report_rules(res.record, kinds, doc_hash, reference=reference)

    if cost:
        print(f"\nCOST             ${cost:.4f} for {pages} page(s) at "
              f"${USD_PER_PAGE}/page  ({costguard.report()})")


def _report_rules(record, kinds, doc_hash, reference=None) -> None:
    print("\nCANARY           where did the privileged value come from?")
    fired = canary.check(record, kinds)
    if fired:
        for f in fired:
            print(f"  FIRED  {f.code}: {f.detail[:76]}")
    else:
        print("  nothing fired — no guarded field came from an impossible place")

    print("\nEXTRACTED        what Document AI believes the invoice says")
    for attr in ("vendor_name", "invoice_number", "amount_total", "currency",
                 "bank_account", "tax_rate", "vendor_address"):
        got = (reference or record).get(attr)
        print(f"  {attr:<16} {got!r}")

    decision = baseline_rules.evaluate(reference or record, None)
    gate = gate_evaluate(reference or record, None)
    print(f"\nRULES            {len(decision.findings)} finding(s): "
          f"{', '.join(decision.codes) or 'none'}")
    print(f"GATE             {gate.action.value}  "
          f"({', '.join(gate.codes) or 'no findings'})")
    print("\nA first-time supplier with no history always reaches a person. That is the "
          "correct answer here,\nand it is what the gate is for.")


if __name__ == "__main__":
    main()
