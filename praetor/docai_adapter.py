"""Document AI's answer, turned into spans the kernel accepts.

This closes `DECISIONS.md` #9 — the project's largest admitted gap. Until now the reader
consumed pre-segmented annotations, so a real invoice arriving as a PDF had no spans and
nothing downstream could run. The system had no front door.

Document AI's Invoice Parser returns entities carrying
`pageAnchor.boundingPoly.normalizedVertices` — normalised 0–1 coordinates, the same shape
`praetor/docile_adapter.py` already consumes — so the kernel needs no changes at all. It
is the adapter that has to be careful, in three places.

## 1. The reader is shown every line, not just the fields Document AI found

Spans come from the page's **lines**, not from its entities. Offering only entity spans
would mean an injected footer — which Document AI has no reason to label as anything —
is never put in front of the reader at all. The attack would then fail because we hid
the payload, not because anything defended against it, and every measurement taken that
way would be flattering and false. The reader sees the whole document, exactly as before.

## 2. `receiver_*` is never mapped, and that is a correctness rule rather than tidiness

On an invoice the **supplier** is who you pay and the **receiver** is you. Mapping
`receiver_name` onto `vendor_name` would put the buyer's own details into the vendor
master and into every downstream comparison. Only `supplier_*` fields map, and anything
unmapped simply is not a field — it is still a span the reader may point at.

Observed while building this: with no "Bill to" block on the page, Document AI could not
tell the two apart and labelled our supplier `receiver_name` at 0.66 confidence. With the
buyer printed, it labelled `supplier_name` correctly — at **0.047 confidence**. The value
was right and the model was unsure, which is worth stating plainly: a system that gates
autonomy on model confidence would have thrown away a correct answer. Nothing here reads
`confidence` at all.

## 3. The honest weakening of the canary, stated rather than discovered later

`praetor/canary.py` asks which *kind* of span a privileged value came from, and refuses a
bank account lifted out of prose. That check is only as trustworthy as the labels.

With DocILE-style annotations the label is ground truth. **Here the label is produced by a
model reading a document the attacker controls.** So an attacker who can get Document AI
to label their injected line as `supplier_iban` gets past the canary — which was
impossible when labels came from annotations.

This is a real reduction in the guarantee and it should be said out loud. What survives:
the attacker must now defeat *two* models that fail differently — persuade the reader to
point at their line **and** persuade a layout-driven extractor to label that line a
payment field — rather than one. "Structurally impossible" becomes "requires both", which
is weaker and still much stronger than the value simply flowing through.

Standard library only, like the rest of `praetor/`. The client that calls the API takes a
dependency and lives outside the kernel; this file only ever sees parsed JSON.
"""
from __future__ import annotations

import hashlib
import json

from praetor.docile_adapter import _span_id
from praetor.types import Field, InvoiceRecord, Provenance

# Document AI Invoice Parser entity type -> our record attribute.
#
# Verified against a live `pretrained-invoice-v1.3` response, not from documentation.
FIELD_MAP: dict[str, str] = {
    "supplier_name": "vendor_name",
    "supplier_address": "vendor_address",
    "invoice_id": "invoice_number",
    "total_amount": "amount_total",
    "currency": "currency",
    "supplier_iban": "bank_account",
    "vat": "tax_rate",
    "vat_tax_rate": "tax_rate",
}

# Deliberately unmapped, and listed rather than merely absent so that adding one is a
# decision somebody has to make on purpose. These describe the buyer, not the supplier.
NEVER_MAPPED: frozenset[str] = frozenset({
    "receiver_name", "receiver_address", "receiver_tax_id", "ship_to_name",
    "ship_to_address", "remit_to_name", "remit_to_address",
    # The buyer's own account. Never a destination for the buyer's own payment, and
    # listed here so that "we never mapped it" is a decision rather than an oversight.
    "receiver_iban",
})

# Document AI's span vocabulary -> the one the kernel speaks.
#
# This is not cosmetic, and its absence was a live defect. `praetor/canary.py` allows a
# bank account to come from a span the document labels `payment_iban`, which is the
# DocILE vocabulary `praetor/docile_adapter.py` emits. Document AI calls the same thing
# `supplier_iban`, so on the Document AI path every clean invoice tripped
# IMPOSSIBLE_ORIGIN -- a 100% false-positive rate on the only path that reads real PDFs.
# Phase 2 measured fields extracted, not origins, so nothing caught it.
#
# The translation belongs here rather than in the kernel. A canary holding a union of
# every vendor's vocabulary grows a new entry per adapter, and the entry nobody
# remembers to add is the one that silently changes behaviour. One vocabulary in the
# kernel; each adapter speaks it.
#
# An unmapped kind passes through unchanged and therefore does NOT satisfy the
# allowlist, so a payment field this map has not learned escalates rather than paying.
# That is the right direction to be wrong in, and it is why this map may stay short.
SPAN_KIND_MAP: dict[str, str] = {
    "supplier_iban": "payment_iban",
    # Added when praetor/canary.py started guarding `amount_total` as well. Document AI
    # calls the total `total_amount`; the kernel's vocabulary is `amount_total`, and
    # without this line every clean Document AI invoice tripped IMPOSSIBLE_ORIGIN on the
    # total -- the identical defect to `supplier_iban`, on the next field to be guarded.
    #
    # **Guarding a new field means auditing this map.** That is the rule this table has
    # now taught twice.
    "total_amount": "amount_total",
}


def _text(document: dict, layout: dict) -> str:
    """Resolve a layout's text anchor against the document's full text."""
    full = document.get("text") or ""
    out = []
    for seg in (layout.get("textAnchor") or {}).get("textSegments") or []:
        start = int(seg.get("startIndex") or 0)
        end = int(seg.get("endIndex") or 0)
        out.append(full[start:end])
    return "".join(out).strip()


def _bbox(poly: dict | None) -> list[float] | None:
    """The normalised vertices, as [left, top, right, bottom]."""
    verts = (poly or {}).get("normalizedVertices") or []
    xs = [float(v.get("x", 0.0)) for v in verts]
    ys = [float(v.get("y", 0.0)) for v in verts]
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _ranges(anchor: dict | None) -> list[tuple[int, int]]:
    out = []
    for seg in (anchor or {}).get("textSegments") or []:
        out.append((int(seg.get("startIndex") or 0), int(seg.get("endIndex") or 0)))
    return out


def _entity_kinds(document: dict) -> list[tuple[int, int, str]]:
    """(start, end, type) for every entity, so a line can be matched by character range.

    Matched on text ranges rather than on overlapping boxes. Geometry needs a threshold,
    and a threshold on a security-relevant label is a knob somebody eventually tunes
    until the check stops firing.
    """
    out = []
    for entity in document.get("entities") or []:
        etype = str(entity.get("type") or "")
        if not etype:
            continue
        for start, end in _ranges(entity.get("textAnchor")):
            if end > start:
                out.append((start, end, etype))
    return out


def spans_of(document: dict, doc_hash: str = "") -> dict[str, str]:
    """Every line on the page: span_id -> text. This is what the reader is shown."""
    out: dict[str, str] = {}
    for page in document.get("pages") or []:
        number = int(page.get("pageNumber") or 1) - 1
        for line in page.get("lines") or []:
            layout = line.get("layout") or {}
            bbox = _bbox(layout.get("boundingPoly"))
            text = _text(document, layout)
            if bbox is None or not text:
                continue
            out[_span_id(number, bbox)] = text
    return out


def span_kinds_of(document: dict) -> dict[str, str]:
    """span_id -> the field type Document AI assigned, or 'other' for ordinary text.

    'other' is the honest label for a line no entity claims, and it is what
    `praetor/canary.py` treats as prose. Read the module docstring on what that label is
    now worth: it comes from a model, not from ground truth.

    Types are translated through `SPAN_KIND_MAP` into the vocabulary the kernel speaks,
    so the canary compares like with like. See that map for what went wrong without it.
    """
    entities = _entity_kinds(document)
    kinds: dict[str, str] = {}
    for page in document.get("pages") or []:
        number = int(page.get("pageNumber") or 1) - 1
        for line in page.get("lines") or []:
            layout = line.get("layout") or {}
            bbox = _bbox(layout.get("boundingPoly"))
            if bbox is None or not _text(document, layout):
                continue
            kind = "other"
            for lstart, lend in _ranges(layout.get("textAnchor")):
                for estart, eend, etype in entities:
                    if lstart < eend and estart < lend:      # ranges overlap
                        kind = etype
                        break
                if kind != "other":
                    break
            kinds[_span_id(number, bbox)] = SPAN_KIND_MAP.get(kind, kind)
    return kinds


def content_hash(document: dict) -> str:
    """A stable fingerprint of a parsed document.

    `eval/run_pdf.py` built this with Python's built-in `hash()`, which is salted per
    process: the same invoice produced a different `doc_hash` on every run. That is
    harmless for a script that prints it once and fatal for the thing it is for --
    DECISIONS #10 keeps the hash so the provenance of a paid value is answerable from a
    trace months later, and a value that changes every process answers nothing.

    `praetor/docile_adapter.py` has always used sha256 over the annotation bytes. This is
    the same guarantee for the Document AI path, over the parsed response so that
    re-parsing the identical PDF grounds against the identical document.
    """
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def to_record(document: dict, doc_hash: str, doc_id: str) -> InvoiceRecord:
    """What Document AI believes the invoice says.

    This is a *reference*, for scoring extraction and for the rules to run against. It is
    not how a value reaches a payment: that path still goes reader -> resolver, so the
    grounding guarantee is untouched by anything in this file.
    """
    record = InvoiceRecord(doc_id=doc_id)
    for entity in document.get("entities") or []:
        etype = str(entity.get("type") or "")
        if etype in NEVER_MAPPED:
            continue
        attr = FIELD_MAP.get(etype)
        if not attr or getattr(record, attr, None) is not None:
            continue
        value = str(entity.get("mentionText") or "").strip()
        if not value:
            continue
        refs = ((entity.get("pageAnchor") or {}).get("pageRefs") or [{}])
        bbox = _bbox(refs[0].get("boundingPoly"))
        page = int(refs[0].get("page") or 0)
        setattr(record, attr, Field(
            value=value,
            prov=Provenance(doc_hash=doc_hash,
                            span_id=_span_id(page, bbox) if bbox else None,
                            tainted=True),
        ))
    return record


def unmapped_types(document: dict) -> set[str]:
    """Entity types this adapter ignores. Worth printing when a new parser version ships:
    a type we do not know about is a field silently not arriving."""
    return {str(e.get("type") or "") for e in document.get("entities") or []
            if str(e.get("type") or "") not in FIELD_MAP} - {""}
