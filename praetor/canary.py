"""The canary: a value that arrived from somewhere it could not legitimately come from.

The resolver (`praetor/resolver.py`) guarantees that a value is a real span in the real
document. It deliberately does not care *which* span. That gap is the one an attacker who
controls the document actually uses: plant a sentence in the footer, get the reader to
point at it, and the value is now genuinely present in the document and genuinely
tainted -- which is exactly what the resolver was built to allow.

This file closes the half of that gap which is decidable without reading anything.

A bank account is printed in a payment block. It is not printed in a free-text note, on
any real invoice, ever. The same is true of the invoice total. So a `bank_account` resolved from a span the document itself
labels as prose is not a suspicious value -- it is a structurally impossible one, and it
stays impossible no matter how convincing the sentence is. That is the property worth
having: **the check never reads the note, so nothing written in the note can change the
outcome.** Every other defence in this repo can at least be argued with. This one cannot
be addressed by the attacker at all, because it is not looking at their text.

It is roughly thirty lines and contains no model, which is the point. It sits inside the
guarantee.

**What it costs.** An allowlist fails closed, so a document that labels its payment block
unusually -- bad OCR, an unmapped field type, a layout nobody has seen -- gets escalated
rather than paid. On a privileged field that is the direction to fail in, but it is a
real cost and it lands as human touches. It is also scoped: it protects fields that have
a structural home on the page. It says nothing about a plausible sentence sitting in the
place a note is supposed to be.
"""
from __future__ import annotations

from praetor.guard import Grounded, Origin, check_origins
from praetor.types import Finding, InvoiceRecord

# Fields where the origin is worth constraining. These are the ones where being wrong
# moves money rather than raising a query.
GUARDED_FIELDS: frozenset[str] = frozenset({"bank_account", "amount_total"})

# Span kinds a guarded field may legitimately be lifted from, by the document's own
# labelling. Keyed by our record attribute, valued in DocILE-style fieldtypes -- the
# same vocabulary `praetor/docile_adapter.py` maps from.
#
# An allowlist rather than a blocklist, deliberately. A blocklist of "note", "other",
# "footer" fails open on the first field type nobody thought of, and the whole reason
# this file exists is that the attacker chooses where their text sits.
LEGITIMATE_ORIGINS: dict[str, frozenset[str]] = {
    "bank_account": frozenset({"payment_iban", "payment_bank_account"}),
    # The second field that moves money. A wrong vendor name raises a query; a wrong
    # total pays the wrong amount to the right account, and it is the quieter fraud --
    # nobody notices a supplier being overpaid 8% the way they notice an unknown account.
    #
    # `line_item_amount` is deliberately NOT permitted. A total lifted from one line of
    # the table is wrong by construction, and until `constructed_v2` this corpus had no
    # line items, so the mistake could not even be expressed (FINDINGS §28).
    "amount_total": frozenset({"amount_total"}),
}

# Deliberately NOT guarded: vendor_name, vendor_address, invoice_number, currency,
# tax_rate. The origin check costs a human touch every time it fires, and on those
# fields being wrong raises a query rather than moving money. Guarding everything would
# buy very little and spend the one thing this system is short of, which is a person's
# attention. This list is the judgement, and it is here to be argued with.


def check(record: InvoiceRecord, span_kinds: dict[str, str]) -> list[Finding]:
    """Findings for guarded fields that came from an impossible place.

    The comparison itself lives in `praetor/guard.py`, because it is not an invoice
    idea -- any document pipeline with labelled spans wants it. What is invoice
    knowledge, and stays here, is *which* fields are worth guarding and *what* counts as
    a legitimate home for them.

    A span id absent from `span_kinds` is treated as unknown origin and fires, because
    "we could not establish where this came from" and "this came from somewhere
    legitimate" must not produce the same outcome on a field that moves money.
    """
    values: dict[str, Grounded] = {}
    for attr in sorted(GUARDED_FIELDS):
        fld = getattr(record, attr, None)
        if fld is None or fld.prov.span_id is None:
            continue
        values[attr] = Grounded(
            value=fld.value,
            origin=Origin(doc_hash=fld.prov.doc_hash, span_id=fld.prov.span_id,
                          kind=span_kinds.get(fld.prov.span_id),
                          tainted=fld.prov.tainted),
        )

    codes = {"unknown_origin": "ORIGIN_UNKNOWN",
             "origin_not_permitted": "IMPOSSIBLE_ORIGIN"}
    return [Finding(codes[v.reason], v.field, v.detail)
            for v in check_origins(values, LEGITIMATE_ORIGINS).values()]
