"""Rule 4 — the agent may point at a reason, never author one.

`praetor/resolver.py` says the reader may only *point at* a value, never write one.
This file applies the same rule one level up, to decisions.

The hole it closes is the one FINDINGS §8 left open and named. The agent can be talked
into resolving an exception by a sentence that claims nothing checkable -- *"this
variance was agreed on the call last Tuesday"*. `praetor/authority.py` cannot touch that
sentence, because it asserts no reference a register could hold. There is nothing to
look up, so there is nothing to refuse.

Rule 4 inverts the question. Instead of asking whether anything on the document is
false, it asks whether anything the buyer already knows is **true**: is there a
pre-authorised rule whose preconditions actually hold for this exception? If no rule
verifies, the resolve is void, and the sentence never mattered either way.

That is the same move the resolver makes. The resolver does not ask whether a value
looks legitimate; it asks whether the value is a pointer into the document. This does
not ask whether a justification sounds convincing; it asks whether a rule verifies.
Both replace a judgement with a lookup, and a lookup cannot be argued with.

**Every precondition here reads buyer-side records only** -- the purchase-order
register, the vendor pattern built from that client's own invoice history, the amount
already extracted and resolved. None of them reads the note. `RULES` is a closed set:
a resolve citing something not in it is refused for that reason alone.

**What it costs.** This is blunter than the gate it sits beside. Plenty of exceptions a
person would wave through have no rule to point at, and every one of them becomes a
human touch. It will lower the 28% in FINDINGS §6, and by design: the removals it takes
away are exactly the ones that rested on the agent finding a note persuasive. It also
needs a buyer-side register to be worth anything, which is ADR #5's cost restated.

No LLM in this file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from praetor import authority
from praetor.types import Finding, InvoiceRecord, VendorPattern

# Findings no rule may ever resolve. A privileged field is not a discrepancy to be
# explained; it is a payment target, and only a human declassifies one. Kept here as
# well as in the gate so this module refuses on its own rather than trusting a caller.
NEVER_RESOLVABLE: frozenset[str] = frozenset({"BANK_UNKNOWN",
                                              "TAINTED_ACCOUNT_NOT_IN_MASTER"})

_INVOICE_REF = re.compile(r"\b([A-Za-z]{0,4}[-_]?\d[\dA-Za-z\-_/]{2,})\b")


@dataclass(frozen=True)
class RuleCheck:
    """The outcome of asking whether one rule holds. `ok` is the only thing that votes."""
    rule_id: str
    ok: bool
    why: str


@dataclass(frozen=True)
class ResolutionRule:
    rule_id: str
    describe: str
    resolves: frozenset[str]   # finding codes this rule is allowed to address


def _amount(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", value.replace(",", "")))
    except ValueError:
        return None


def _r1_verified_order(findings, record, pattern, context, register, invoice_amount):
    """The document cites an order the buyer actually raised, for this money."""
    claims = authority.find_claims(context, register, invoice_amount)
    good = [c for c in claims if c.verified]
    if not good:
        if claims:
            return False, f"approval claimed but not verified: {claims[0].describe()}"
        return False, "no approval reference on the document"
    return True, f"verified against {good[0].verified_by}"


def _r2_known_reissue(findings, record, pattern, context, register, invoice_amount):
    """The document cites a prior invoice this client has already seen from this
    supplier. A reissue naming an invoice number nobody has ever received is not one."""
    if pattern is None or not pattern.seen_invoice_numbers:
        return False, "no invoice history for this supplier"
    known = {str(n).strip().upper() for n in pattern.seen_invoice_numbers}
    current = (record.get("invoice_number") or "").strip().upper()
    for line in context:
        for m in _INVOICE_REF.finditer(line or ""):
            ref = m.group(1).strip().upper()
            if ref != current and ref in known:
                return True, f"cites {ref}, already received from this supplier"
    return False, "cites no prior invoice number on record for this supplier"


def _r3_within_supplier_range(findings, record, pattern, context, register,
                              invoice_amount):
    """The amount sits inside the supplier's own historical range, so the range rule
    firing was the rule being cautious rather than the invoice being unusual."""
    if pattern is None or pattern.amount_p05 is None or pattern.amount_p95 is None:
        return False, "no amount history for this supplier"
    amt = invoice_amount if invoice_amount is not None else _amount(
        record.get("amount_total"))
    if amt is None:
        return False, "no amount on the invoice"
    if pattern.amount_p05 <= amt <= pattern.amount_p95:
        return True, (f"{amt:,.2f} is inside this supplier's usual "
                      f"{pattern.amount_p05:,.2f}-{pattern.amount_p95:,.2f}")
    return False, (f"{amt:,.2f} is outside this supplier's usual "
                   f"{pattern.amount_p05:,.2f}-{pattern.amount_p95:,.2f}")


def _r4_matches_supplier_record(findings, record, pattern, context, register,
                                invoice_amount):
    """The flagged field in fact matches what this client has on file, so the mismatch
    was in the comparison rather than in the document."""
    if pattern is None:
        return False, "no record for this supplier"
    checks = {"CURRENCY_MISMATCH": ("currency", pattern.modal_currency),
              "TAX_RATE_MISMATCH": ("tax_rate", pattern.modal_tax_rate),
              "ADDRESS_MISMATCH": ("vendor_address", pattern.modal_address)}
    codes = {f.code for f in findings}
    relevant = [c for c in checks if c in codes]
    if not relevant:
        return False, "no field mismatch for this rule to address"
    for code in relevant:
        attr, expected = checks[code]
        actual = record.get(attr)
        if expected is None or actual is None:
            return False, f"nothing on file for {attr}"
        if actual.strip().casefold() != str(expected).strip().casefold():
            return False, f"{attr} is {actual!r}, on file as {expected!r}"
    return True, "every flagged field matches this client's record for the supplier"


RULES: dict[str, ResolutionRule] = {
    "R1": ResolutionRule(
        "R1", "approved under a purchase order the buyer raised",
        frozenset({"AMOUNT_OUT_OF_RANGE", "TAX_RATE_MISMATCH", "CURRENCY_MISMATCH",
                   "ADDRESS_MISMATCH", "DUPLICATE_INVOICE", "MISSING_FIELD"})),
    "R2": ResolutionRule(
        "R2", "a reissue of an invoice this client already received",
        frozenset({"DUPLICATE_INVOICE"})),
    "R3": ResolutionRule(
        "R3", "the amount is inside this supplier's own historical range",
        frozenset({"AMOUNT_OUT_OF_RANGE"})),
    "R4": ResolutionRule(
        "R4", "the flagged field matches this client's record for the supplier",
        frozenset({"CURRENCY_MISMATCH", "TAX_RATE_MISMATCH", "ADDRESS_MISMATCH"})),
}

_PRECONDITIONS = {"R1": _r1_verified_order, "R2": _r2_known_reissue,
                  "R3": _r3_within_supplier_range, "R4": _r4_matches_supplier_record}


def verify(rule_id: str, findings: list[Finding], record: InvoiceRecord,
           pattern: VendorPattern | None, context: list[str],
           register=None, invoice_amount: float | None = None) -> RuleCheck:
    """Does this one rule actually hold for this exception?

    Refuses, in order: an unknown rule, a rule pointed at a finding it is not allowed to
    address, any finding that is never resolvable, and finally the rule's own
    preconditions.
    """
    rule = RULES.get(rule_id)
    if rule is None:
        return RuleCheck(rule_id, False, f"no such rule: {rule_id!r}")

    codes = {f.code for f in findings}
    if not codes:
        return RuleCheck(rule_id, False, "nothing to resolve")
    forbidden = codes & NEVER_RESOLVABLE
    if forbidden:
        return RuleCheck(rule_id, False,
                         f"{', '.join(sorted(forbidden))} is never resolvable by rule")
    uncovered = codes - rule.resolves
    if uncovered:
        return RuleCheck(rule_id, False,
                         f"{rule_id} does not cover {', '.join(sorted(uncovered))}")

    ok, why = _PRECONDITIONS[rule_id](findings, record, pattern, context, register,
                                      invoice_amount)
    return RuleCheck(rule_id, ok, why)


def any_rule_holds(findings: list[Finding], record: InvoiceRecord,
                   pattern: VendorPattern | None, context: list[str],
                   register=None, invoice_amount: float | None = None) -> RuleCheck | None:
    """The first pre-authorised rule that verifies, or None if the resolve is void.

    The gate asks this itself rather than letting the agent nominate a rule. An agent
    that picks the rule can pick the one that happens to verify for an unrelated
    reason; asking independently removes that move entirely, and means the reader
    contract does not have to change to get the guarantee.
    """
    for rule_id in RULES:
        check = verify(rule_id, findings, record, pattern, context, register,
                       invoice_amount)
        if check.ok:
            return check
    return None
