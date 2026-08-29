"""The rules baseline.

Deliberately written BEFORE any agent code: this is what the agent has to beat.
If the agent cannot beat exact-match-plus-tolerance, we learn that on day 2 rather
than from a judge.

No AI anywhere in this file, by design.
"""
from __future__ import annotations

import re

from praetor import trace
from praetor.types import Decision, Finding, InvoiceRecord, VendorPattern, Verdict

# How far outside a vendor's historical range an amount may fall before we flag it.
AMOUNT_TOLERANCE = 0.25

# A field counts as expected when this vendor supplies it on at least this share
# of their other invoices. Learned per vendor rather than hardcoded, so the rules
# transfer across corpora with different field sets.
EXPECTED_PRESENCE = 0.8

CHECKED_FIELDS = ("vendor_name", "invoice_number", "amount_total",
                  "bank_account", "vendor_address")

# How far the line items may miss the stated total before it is a finding. Real invoices
# carry rounding, a shipping line the parser missed, or a discount applied to the total.
# Generous on purpose: this rule exists to catch a total that was altered, not to argue
# about a cent.
SUM_TOLERANCE = 0.02


def _norm(s: str | None) -> str:
    """Loose normalisation for comparing free text like addresses."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _norm_acct(s: str | None) -> str:
    """Bank accounts differ only by punctuation and case across documents."""
    if not s:
        return ""
    return re.sub(r"[^A-Za-z0-9]+", "", s).upper()


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", s.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _line_items_sum(record: InvoiceRecord) -> Finding | None:
    """The invoice shows its working. Do the lines add up to the total it states?

    Every other rule in this file compares the document against the SUPPLIER'S HISTORY,
    so all of them need a known vendor and enough past invoices. This one compares the
    document against itself, which means it works on a first-time supplier, on a corpus
    with no history at all, and on a document whose vendor nobody recognises -- the
    cases where every other rule here is silent.

    FINDINGS §28 measured the gap: on a corpus with line items, an altered total was
    caught 1 time in 5 and the reason was right 0 times. There was no arithmetic
    anywhere in this system.
    """
    if len(record.line_item_amounts) < 2:
        return None                      # nothing to add up, or nothing to check against
    stated = _to_float(record.get("amount_total"))
    if stated is None:
        return None
    parts = [_to_float(f.value) for f in record.line_item_amounts]
    if any(p is None for p in parts):
        # A line we could not read is not a discrepancy. Claiming one would be a finding
        # about our own OCR, and it would fire on every scanned document.
        return None
    summed = sum(parts)                                   # type: ignore[arg-type]
    if stated == 0 or abs(summed - stated) <= max(abs(stated) * SUM_TOLERANCE, 0.01):
        return None
    return Finding(
        "LINE_ITEMS_DO_NOT_SUM", "amount_total",
        f"{len(parts)} line items total {summed:,.2f}, the invoice states {stated:,.2f}")


def evaluate(record: InvoiceRecord, pattern: VendorPattern | None) -> Decision:
    """Classify one invoice as PASS or EXCEPTION against its vendor's own history."""
    findings: list[Finding] = []

    # Runs before the vendor check, because it is the one rule here that does not need a
    # vendor. An unknown supplier whose invoice does not add up should say both things.
    arithmetic = _line_items_sum(record)
    if arithmetic is not None:
        findings.append(arithmetic)

    if pattern is None or pattern.n_invoices == 0:
        findings.append(
            Finding("UNKNOWN_VENDOR", "vendor_name", "no prior invoices for this vendor")
        )
        return Decision(record.doc_id, Verdict.EXCEPTION, findings)

    # A missing field is only an exception if this vendor normally provides it.
    for name in CHECKED_FIELDS:
        if record.get(name):
            continue
        if pattern.field_presence.get(name, 0.0) >= EXPECTED_PRESENCE:
            findings.append(Finding(
                "MISSING_FIELD", name,
                f"{name} absent, but present on "
                f"{pattern.field_presence[name] * 100:.0f}% of this vendor's invoices",
            ))

    acct = _norm_acct(record.get("bank_account"))
    if acct:
        known = {_norm_acct(a) for a in pattern.bank_accounts}
        if acct not in known:
            findings.append(
                Finding("BANK_UNKNOWN", "bank_account",
                        "account not seen on any prior invoice from this vendor")
            )

    inv_no = record.get("invoice_number")
    if inv_no and inv_no in pattern.seen_invoice_numbers:
        findings.append(
            Finding("DUPLICATE_INVOICE", "invoice_number", f"{inv_no} already processed")
        )

    cur = record.get("currency")
    if cur and pattern.modal_currency and cur.upper() != pattern.modal_currency.upper():
        findings.append(
            Finding("CURRENCY_MISMATCH", "currency",
                    f"{cur} vs usual {pattern.modal_currency}")
        )

    tax = record.get("tax_rate")
    if tax and pattern.modal_tax_rate and _norm(tax) != _norm(pattern.modal_tax_rate):
        findings.append(
            Finding("TAX_RATE_MISMATCH", "tax_rate",
                    f"{tax} vs usual {pattern.modal_tax_rate}")
        )

    addr = _norm(record.get("vendor_address"))
    if addr and pattern.modal_address and addr != _norm(pattern.modal_address):
        findings.append(
            Finding("ADDRESS_MISMATCH", "vendor_address", "differs from usual address")
        )

    amt = _to_float(record.get("amount_total"))
    if amt is not None and pattern.amount_p05 is not None and pattern.amount_p95 is not None:
        lo = pattern.amount_p05 * (1 - AMOUNT_TOLERANCE)
        hi = pattern.amount_p95 * (1 + AMOUNT_TOLERANCE)
        if amt < lo or amt > hi:
            findings.append(
                Finding("AMOUNT_OUT_OF_RANGE", "amount_total",
                        f"{amt:.2f} outside usual {lo:.2f}-{hi:.2f}")
            )

    verdict = Verdict.EXCEPTION if findings else Verdict.PASS
    with trace.span("rules.evaluate",
                    **{"praetor.doc_id": record.doc_id,
                       "praetor.tenant": record.tenant_id or "",
                       "praetor.verdict": verdict.value,
                       "praetor.findings": ",".join(f.code for f in findings),
                       "praetor.peer_invoices": pattern.n_invoices,
                       **{f"praetor.account.{k.split('.')[-1]}": v
                          for k, v in trace.taint(record.bank_account).items()}}):
        pass
    return Decision(record.doc_id, verdict, findings)
