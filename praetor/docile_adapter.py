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
