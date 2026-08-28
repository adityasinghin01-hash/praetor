"""Turn the reader's span references back into values.

This file is where "the model handles references, never values" becomes true
rather than aspirational. The quarantined reader is only ever allowed to emit
span IDs. This resolver looks those IDs up in the immutable document and rejects
anything that does not correspond to a real span.

Consequence: the model cannot introduce a bank account that is not physically
present in the document. It can still *point at the wrong span* — an attacker who
controls the document can plant one — which is what the policy gate is for.

No LLM in this file, by design.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from praetor import trace
from praetor.guard import Guard, is_reference
from praetor.types import Field, InvoiceRecord, Provenance


class ResolutionError(ValueError):
    """The reader emitted something that is not a resolvable span reference."""


@dataclass
class Resolution:
    record: InvoiceRecord
    rejected: dict[str, str] = field(default_factory=dict)  # attr -> why

    @property
    def clean(self) -> bool:
        return not self.rejected


def looks_like_span_id(value: str) -> bool:
    """Kept as the invoice layer's name for `guard.is_reference`."""
    return is_reference(value)


def resolve(
    reader_output: dict[str, str],
    spans: dict[str, str],
    doc_hash: str,
    doc_id: str,
) -> Resolution:
    """Map {attr: span_id} to an InvoiceRecord of tainted values.

    Anything that is not a valid, known span ID is rejected and never reaches the
    record. A model that tries to answer with a literal value instead of a
    reference fails here — which is the point.
    """
    res = Resolution(record=InvoiceRecord(doc_id=doc_id))

    with trace.span("resolve", **{"praetor.doc_id": doc_id,
                                  "praetor.doc_hash": doc_hash,
                                  "praetor.spans_offered": len(spans)}) as sp:
        _resolve_into(res, reader_output, spans, doc_hash)
        sp.set_attribute("praetor.fields_resolved",
                         sum(1 for a in ("vendor_name", "invoice_number", "amount_total",
                                         "currency", "bank_account", "tax_rate",
                                         "vendor_address")
                             if getattr(res.record, a) is not None))
        sp.set_attribute("praetor.fields_rejected", len(res.rejected))
        if res.rejected:
            # The model tried to hand back something that was not a reference. Worth
            # finding in a trace months later.
            sp.set_attribute("praetor.rejected", json.dumps(res.rejected)[:900])
    return res


def _resolve_into(res, reader_output, spans, doc_hash) -> None:
    """Which field names exist is invoice knowledge; the grounding is not.

    Everything below the field-name check is `praetor/guard.py` -- the same mechanism a
    caller with no invoices gets. Delegating rather than reimplementing is the point:
    two copies of a security check are two things that can drift apart, and the one that
    drifts is always the one nobody is looking at.
    """
    known: dict[str, object] = {}
    for attr, raw in reader_output.items():
        if not hasattr(res.record, attr):
            res.rejected[attr] = "unknown field"
        else:
            known[attr] = raw

    result = Guard(spans, doc_hash=doc_hash, doc_id=res.record.doc_id).ground(known)
    res.rejected.update(result.refused)
    for attr, grounded in result.values.items():
        setattr(res.record, attr, Field(
            value=grounded.value,
            prov=Provenance(doc_hash=grounded.origin.doc_hash,
                            span_id=grounded.origin.span_id,
                            tainted=grounded.origin.tainted),
        ))
