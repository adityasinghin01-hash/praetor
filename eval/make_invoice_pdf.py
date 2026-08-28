"""Render a corpus invoice as an actual PDF, so the front door can be tested on one.

`DECISIONS.md` #9 is the project's largest admitted gap: the reader consumes
pre-segmented annotations, so **a real invoice arriving as a PDF has no spans and nothing
downstream can run.** Closing it means putting a real document through Document AI and
getting spans back.

That needs a real document. The corpus is annotations, not files — so this renders one
back into a page and prints it. The result is a genuine PDF that Document AI has to read
like any other: no annotations travel with it, no coordinates, nothing but ink.

**Why this is a fair test and not a rigged one.** The content is synthetic and we know the
ground truth, which is exactly what makes it useful: we can score what Document AI
extracted against what we printed. What we are testing is the *front door* — does a real
file become spans the kernel accepts — and for that, a PDF we generated is as opaque to
Document AI as one a supplier sent. It is not a test of Document AI's accuracy on real
supplier layouts, and §9 stays open until real documents go through.

Uses headless Chrome, which `docs/render.py` already depends on, so no new dependency.

    python eval/make_invoice_pdf.py V000_003 --out out/pdf/V000_003.pdf
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# A4 at 96 CSS px per inch. The corpus stores bboxes as fractions of the page, so
# multiplying by these puts every field where the annotation says it is.
PAGE_W, PAGE_H = 794, 1123

LABELS = {
    "vendor_name": None,                     # printed large, no label
    "vendor_address": None,
    "invoice_id": "Invoice no.",
    "invoice_date": "Date",
    "amount_total": "Total due",
    "currency_code_amount_due": "Currency",
    "tax_detail_rate": "VAT",
    "payment_iban": "Pay to (IBAN)",
    "other": None,
}

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; width: %dpx; height: %dpx; position: relative;
       font: 12px/1.35 "Helvetica Neue", Helvetica, Arial, sans-serif; color: #111;
       -webkit-print-color-adjust: exact; }
.f { position: absolute; }
.lab { display: block; font-size: 8px; letter-spacing: .08em; text-transform: uppercase;
       color: #777; margin-bottom: 2px; }
.val { display: block; white-space: nowrap; }
.vendor_name .val { font-size: 19px; font-weight: 700; letter-spacing: -.01em; }
.amount_total .val { font-size: 15px; font-weight: 700; }
.payment_iban .val { font-family: "Courier New", monospace; }
.billto .val, .terms .val { font-size: 11px; }
.other .val { font-size: 10px; color: #333; white-space: normal; font-style: italic; }
.rule { position: absolute; left: 6%%; right: 6%%; height: 1px; background: #ccc; }
""" % (PAGE_W, PAGE_H)


# The buyer. Printed because leaving it off makes the document genuinely ambiguous:
# with only one company on the page, Document AI cannot tell the supplier from the
# recipient and labelled ours `receiver_name` at 0.66 confidence. A real invoice always
# names both, and the distinction is not cosmetic here -- mapping a receiver field onto
# the vendor would put the buyer's own details into the vendor master.
BUYER = ["Acme Industries GmbH", "Attn: Accounts Payable",
         "Wilhelmstrasse 14, 10117 Berlin", "Germany"]


def render_html(annotation: dict) -> str:
    parts = [f"<!doctype html><meta charset='utf-8'><style>{CSS}</style><body>"]
    parts.append("<div class='rule' style='top:6.2%'></div>")
    parts.append("<div class='rule' style='top:74%'></div>")
    parts.append(
        "<div class='f billto' style='left:8%;top:26%;width:40%'>"
        "<span class='lab'>Bill to</span>"
        + "".join(f"<span class='val'>{_escape(line)}</span>" for line in BUYER)
        + "</div>")
    parts.append(
        "<div class='f terms' style='left:62%;top:26%;width:30%'>"
        "<span class='lab'>Payment terms</span>"
        "<span class='val'>Net 30 days from invoice date</span></div>")
    for field in annotation.get("field_extractions", []):
        ftype = str(field.get("fieldtype") or "other")
        left, top, right, bottom = field.get("bbox") or [0, 0, 0.2, 0.03]
        label = LABELS.get(ftype, ftype.replace("_", " "))
        text = str(field.get("text", ""))
        style = (f"left:{left * 100:.3f}%;top:{top * 100:.3f}%;"
                 f"width:{max(right - left, 0.02) * 100:.3f}%")
        lab = f"<span class='lab'>{label}</span>" if label else ""
        parts.append(f"<div class='f {ftype}' style='{style}'>{lab}"
                     f"<span class='val'>{_escape(text)}</span></div>")
    parts.append("</body>")
    return "".join(parts)


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def to_pdf(html: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "invoice.html"
        page.write_text(html, encoding="utf-8")
        # --no-pdf-header-footer keeps Chrome from stamping a URL and page number on it,
        # which would otherwise become spans Document AI faithfully reports.
        cmd = [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
               "--no-pdf-header-footer", f"--print-to-pdf={out}", page.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not out.exists() or out.stat().st_size == 0:
        sys.exit(f"Chrome produced no PDF.\n{r.stderr[-600:]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = ROOT / args.annotations / f"{args.doc_id}.json"
    if not src.exists():
        sys.exit(f"no such document: {src}")
    annotation = json.loads(src.read_text())

    out = Path(args.out) if args.out else ROOT / "out" / "pdf" / f"{args.doc_id}.pdf"
    if not out.is_absolute():
        out = ROOT / out
    to_pdf(render_html(annotation), out)

    printed = {f.get("fieldtype"): f.get("text")
               for f in annotation.get("field_extractions", [])}
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
    print(f"layout: {annotation.get('layout', '?')}")
    print("what is on the page (this is the ground truth to score against):")
    for k, v in printed.items():
        print(f"  {k:<28} {str(v)[:60]}")


if __name__ == "__main__":
    main()
