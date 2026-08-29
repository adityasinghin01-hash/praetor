"""Turn DocILE annotations into InvoiceRecords.

DocILE ships per-document annotations with `page`, `bbox` (relative l/t/r/b),
`fieldtype`, and `line_item_id` for line items. Each annotated field therefore
already IS a span — which is why PRAETOR needs no OCR pipeline.

IMPORTANT: DocILE defines 55 fieldtype classes. FIELD_MAP below is our best
reading of the ones we need; it MUST be checked against the real corpus once the
token arrives. `report_unmapped()` exists to make a wrong mapping loud rather
than silent — run it before trusting any numbers.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from praetor import trace
from praetor.types import Field, InvoiceRecord, Provenance

# DocILE fieldtype -> our record attribute. VERIFY against the real corpus.
FIELD_MAP: dict[str, str] = {
    "vendor_name": "vendor_name",
    "invoice_id": "invoice_number",
    "amount_total": "amount_total",
    "currency_code_amount_due": "currency",
    "payment_iban": "bank_account",
    "tax_detail_rate": "tax_rate",
    "vendor_address": "vendor_address",
}


def _span_id(page: int, bbox: list[float]) -> str:
    """Stable identifier for a span. The model may only ever emit one of these."""
    b = "_".join(f"{c:.4f}" for c in bbox)
    return f"p{page}:{b}"


def load_annotation(path: str | Path) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()[:16]


def to_record(annotation: dict, doc_hash: str, doc_id: str) -> InvoiceRecord:
    """Build an InvoiceRecord. Every value carries the span it came from, and is tainted."""
    rec = InvoiceRecord(doc_id=doc_id)
    line_items: set = set()

    for fld in annotation.get("field_extractions", []):
        ftype = fld.get("fieldtype")
        if fld.get("line_item_id") is not None:
            line_items.add(fld["line_item_id"])
        attr = FIELD_MAP.get(ftype)
        if not attr or getattr(rec, attr, None) is not None:
            continue  # first occurrence wins; duplicates are a separate signal
        setattr(rec, attr, Field(
            value=str(fld.get("text", "")).strip(),
            prov=Provenance(
                doc_hash=doc_hash,
                span_id=_span_id(int(fld.get("page", 0)), fld.get("bbox", [0, 0, 0, 0])),
                tainted=True,
            ),
        ))

    rec.line_item_count = len(line_items)

    # The line amounts, in document order, so `praetor/baseline_rules.py` can add them
    # up. Collected in a second pass rather than in the loop above, because that loop
    # takes the FIRST occurrence of each field type and there are deliberately many of
    # these. They carry provenance like everything else.
    for fld in annotation.get("field_extractions", []):
        if fld.get("fieldtype") == "line_item_amount":
            rec.line_item_amounts.append(Field(
                value=str(fld.get("text", "")).strip(),
                prov=Provenance(
                    doc_hash=doc_hash,
                    span_id=_span_id(int(fld.get("page", 0)), fld.get("bbox", [0, 0, 0, 0])),
                    tainted=True,
                )))

    # The moment values acquire provenance. Everything downstream inherits the taint
    # recorded here, so this is where a trace should be able to start.
    with trace.span("extract",
                    **{"praetor.doc_id": doc_id,
                       "praetor.doc_hash": doc_hash,
                       "praetor.spans_seen": len(annotation.get("field_extractions", [])),
                       "praetor.line_items": rec.line_item_count,
                       "praetor.tainted": True}):
        pass
    return rec


def spans_of(annotation: dict, doc_hash: str) -> dict[str, str]:
    """All spans in a document: span_id -> text.

    This is what the quarantined reader is shown. It returns span IDs only, and
    resolver.py looks the text back up here — so the model cannot invent a value.
    """
    out: dict[str, str] = {}
    for fld in annotation.get("field_extractions", []):
        sid = _span_id(int(fld.get("page", 0)), fld.get("bbox", [0, 0, 0, 0]))
        out[sid] = str(fld.get("text", "")).strip()
    return out


# A label a parser emits when it did not classify a region. It is the absence of a
# label, not a claim about one, and it must not be able to overwrite a real one.
UNCLASSIFIED = {"", "other"}


def span_kinds_of(annotation: dict) -> dict[str, str]:
    """span_id -> the document's own field type for that span.

    Same keys as `spans_of`, but the label instead of the text. `praetor/canary.py`
    uses it to ask whether a value arrived from a place it could legitimately come
    from -- a question that can be answered without reading a single character of the
    span, which is why an attacker cannot write their way past it.

    **One region can carry more than one label, and this used to be resolved by
    whichever came last.** Real annotations list a field twice: once with its type and
    again as raw OCR text labelled `other`. Every one of the 300 SROIE receipts does it.
    A plain dict therefore recorded `other` for the total on almost every real document,
    and the canary fired on 289 of 300 -- a 96% false-positive rate on real paper, and
    zero on the synthetic corpus, which has no colliding boxes. It is the same defect
    as the `supplier_iban` mismatch in FINDINGS §20, found the same way: by running on
    documents we did not generate.

    So the labels for one span are combined rather than overwritten:

      * `other` and the empty string are the parser saying nothing, and never win;
      * exactly one real label wins;
      * two DIFFERENT real labels are genuinely ambiguous, and ambiguity on a field
        that moves money has to fail closed, so the span is marked unknown and the
        canary fires.
    """
    # (text -> labels) per span id, and the text `spans_of` would resolve for it.
    # Keeping them together is the point: a label describes the string it was attached
    # to, and the only string that matters is the one the resolver will hand back.
    per_text: dict[str, dict[str, set[str]]] = {}
    winning: dict[str, str] = {}
    for fld in annotation.get("field_extractions", []):
        sid = _span_id(int(fld.get("page", 0)), fld.get("bbox", [0, 0, 0, 0]))
        text = str(fld.get("text", "")).strip()
        per_text.setdefault(sid, {}).setdefault(text, set()).add(
            str(fld.get("fieldtype", "") or ""))
        winning[sid] = text          # last wins, exactly as `spans_of` resolves it

    out: dict[str, str] = {}
    for sid, by_text in per_text.items():
        # Only the labels belonging to the text that actually wins. A label attached to
        # some OTHER string at the same box says nothing about this value.
        labels = by_text.get(winning[sid], set())
        real = {l for l in labels if l not in UNCLASSIFIED}
        if len(real) == 1:
            out[sid] = next(iter(real))
        elif not real:
            out[sid] = "other"
        else:
            # Two different real labels on one string. `__ambiguous__` is in no
            # allowlist, so the origin check refuses it rather than picking one.
            out[sid] = "__ambiguous__"
    return out


def report_unmapped(annotation_dir: str | Path, limit: int = 500) -> Counter:
    """Count fieldtypes we do NOT map. A large count means FIELD_MAP is wrong."""
    seen: Counter = Counter()
    for i, p in enumerate(sorted(Path(annotation_dir).glob("*.json"))):
        if i >= limit:
            break
        ann, _ = load_annotation(p)
        for fld in ann.get("field_extractions", []):
            ft = fld.get("fieldtype")
            if ft and ft not in FIELD_MAP:
                seen[ft] += 1
    return seen


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m praetor.docile_adapter <annotation_dir>")
        print("\nRun this FIRST once DocILE lands — it tells you whether FIELD_MAP is right.")
        raise SystemExit(1)
    counts = report_unmapped(sys.argv[1])
    print(f"mapped fieldtypes:   {sorted(FIELD_MAP)}")
    print(f"unmapped fieldtypes: {len(counts)}")
    for ft, n in counts.most_common(25):
        print(f"  {ft:40} {n}")
