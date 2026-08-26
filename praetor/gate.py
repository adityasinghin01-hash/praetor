"""The policy gate.

Deterministic, non-LLM enforcement sitting between the agent and anything
consequential. Two guarantees it provides, both enforced by tests:

  1. A TAINTED value (anything lifted off a document) cannot become the payment
     target unless it matches a trusted record, or a human declassifies it.
  2. The agent can only ever PROPOSE. Only a human can APPROVE. There is no code
     path by which an agent reaches Action.APPROVED.

Guarantee 2 is also the SOX segregation-of-duties control, which is why the legal
requirement and the security mechanism are the same mechanism here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from praetor import trace
from praetor.tenancy import CrossTenantError
from praetor.types import Finding, InvoiceRecord, VendorPattern

AMOUNT_TOLERANCE = 0.02  # 2% against the PO / expected amount


class Action(str, Enum):
    PROPOSE_PAY = "propose_pay"   # agent's ceiling
    ESCALATE = "escalate"         # needs a human decision
    APPROVED = "approved"         # human only — no agent path reaches this


@dataclass
class GateDecision:
    doc_id: str
    action: Action
    findings: list[Finding] = field(default_factory=list)
    approved_by: str | None = None

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


def _norm_acct(s: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", s or "").upper()


def _amount(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", s.replace(",", "")))
    except ValueError:
        return None


def evaluate(
    record: InvoiceRecord,
    pattern: VendorPattern | None,
    expected_amount: float | None = None,
) -> GateDecision:
    """The agent's ceiling is PROPOSE_PAY. It can never return APPROVED."""
    # Isolation is checked before anything else. A pattern from another client's books
    # cannot be allowed to vouch for this invoice's bank account, and getting that wrong
    # silently is worse than crashing. See praetor/tenancy.py.
    if (pattern is not None and record.tenant_id and pattern.tenant_id
            and record.tenant_id != pattern.tenant_id):
        raise CrossTenantError(
            f"invoice {record.doc_id} belongs to tenant {record.tenant_id!r} but the "
            f"vendor pattern belongs to {pattern.tenant_id!r}")

    findings: list[Finding] = []

    acct_field = record.bank_account
    if acct_field is not None:
        known = {_norm_acct(a) for a in (pattern.bank_accounts if pattern else set())}
        if acct_field.prov.tainted and _norm_acct(acct_field.value) not in known:
            # The core rule: a document-sourced account that we have never seen
            # from this vendor cannot be paid without a human.
            findings.append(Finding(
                "TAINTED_ACCOUNT_NOT_IN_MASTER", "bank_account",
                "account came from the document and is not in the vendor master",
            ))

    amt = _amount(record.get("amount_total"))
    if expected_amount is not None and amt is not None:
        if abs(amt - expected_amount) > expected_amount * AMOUNT_TOLERANCE:
            findings.append(Finding(
                "AMOUNT_OUTSIDE_TOLERANCE", "amount_total",
                f"{amt:.2f} vs expected {expected_amount:.2f}",
            ))

    if pattern is None or pattern.n_invoices == 0:
        findings.append(Finding(
            "FIRST_TIME_VENDOR", "vendor_name",
            "no history for this vendor; first payment always escalates",
        ))

    action = Action.ESCALATE if findings else Action.PROPOSE_PAY
    with trace.span("gate.evaluate",
                    **{"praetor.doc_id": record.doc_id,
                       "praetor.tenant": record.tenant_id or "",
                       "praetor.action": action.value,
                       "praetor.findings": ",".join(f.code for f in findings),
                       **{f"praetor.account.{k.split('.')[-1]}": v
                          for k, v in trace.taint(record.bank_account).items()}}):
        pass
    return GateDecision(record.doc_id, action, findings)


def approve(decision: GateDecision, human_id: str) -> GateDecision:
    """Declassification. The ONLY route to Action.APPROVED, and it needs a person.

    `human_id` must be a real identifier. Agents do not have one, which is what
    makes this boundary enforceable rather than advisory.
    """
    if not human_id or not human_id.strip():
        raise PermissionError("approval requires a human identifier")
    if human_id.startswith("agent:"):
        raise PermissionError("agents cannot approve payments")
    with trace.span("gate.approve",
                    **{"praetor.doc_id": decision.doc_id,
                       "praetor.approved_by": human_id,
                       "praetor.declassified": True}):
        pass
    return GateDecision(
        doc_id=decision.doc_id,
        action=Action.APPROVED,
        findings=decision.findings,
        approved_by=human_id,
    )
