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
import re
from dataclasses import dataclass, field

from praetor import trace
from praetor.types import Field, InvoiceRecord, Provenance

SPAN_ID_RE = re.compile(r"^p\d+:[0-9._]+$")


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
    return bool(SPAN_ID_RE.match(value.strip()))


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
    for attr, raw in reader_output.items():
        if not hasattr(res.record, attr):
            res.rejected[attr] = "unknown field"
            continue
        if raw is None:
            continue
        ref = str(raw).strip()
        if not ref:
            continue

        if not looks_like_span_id(ref):
            # The model emitted a value rather than a reference. This is exactly
            # the failure mode an injected document tries to cause.
            res.rejected[attr] = f"not a span reference: {ref[:40]!r}"
            continue
        if ref not in spans:
            res.rejected[attr] = f"span not present in document: {ref}"
            continue

        setattr(res.record, attr, Field(
            value=spans[ref],
            prov=Provenance(doc_hash=doc_hash, span_id=ref, tainted=True),
        ))
