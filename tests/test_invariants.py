"""Invariants. These are the security claims, expressed as tests.

If any of these fail, PRAETOR's central claims are false. They exist so the claims
are enforced by CI rather than asserted in a README.
"""
import json
from pathlib import Path

import pytest

from praetor.gate import Action, approve, evaluate as gate_evaluate
from praetor.resolver import resolve
from praetor.types import Field, InvoiceRecord, Provenance, VendorPattern

TRUSTED = "IN45-HDFC-0001-7788"
ATTACKER = "IN99-XXXX-6666-0001"
DOC_HASH = "abc123"

# A document as PRAETOR sees it: a set of spans with stable ids.
SPANS = {
    "p0:0.10_0.10_0.40_0.12": "Meridian Supply Co.",
    "p0:0.10_0.20_0.40_0.22": "INV-2291",
    "p0:0.60_0.30_0.90_0.32": "48,200.00",
    "p0:0.10_0.40_0.50_0.42": TRUSTED,
}
SPAN_VENDOR, SPAN_INV, SPAN_AMT, SPAN_ACCT = SPANS.keys()


def _pattern(accounts=(TRUSTED,), n=9) -> VendorPattern:
    return VendorPattern(vendor_key="meridian supply co", n_invoices=n,
                         bank_accounts=set(accounts))


# ---------------------------------------------------------------- resolver

def test_model_cannot_invent_a_value():
    """The whole design rests on this: a literal value is not a reference."""
    res = resolve({"bank_account": ATTACKER}, SPANS, DOC_HASH, "d1")
    assert res.record.bank_account is None
    assert "bank_account" in res.rejected
    assert not res.clean


def test_model_cannot_point_at_a_span_that_does_not_exist():
    res = resolve({"bank_account": "p0:9.99_9.99_9.99_9.99"}, SPANS, DOC_HASH, "d1")
    assert res.record.bank_account is None
    assert "span not present" in res.rejected["bank_account"]


def test_valid_reference_resolves_and_is_tainted():
    res = resolve({"bank_account": SPAN_ACCT}, SPANS, DOC_HASH, "d1")
    assert res.record.bank_account.value == TRUSTED
    assert res.record.bank_account.prov.tainted is True
    assert res.record.bank_account.prov.span_id == SPAN_ACCT
    assert res.clean


def test_every_resolved_value_traces_to_the_document():
    """Nothing downstream may hold a value that is not physically in the document."""
    res = resolve(
        {"vendor_name": SPAN_VENDOR, "invoice_number": SPAN_INV,
         "amount_total": SPAN_AMT, "bank_account": SPAN_ACCT},
        SPANS, DOC_HASH, "d1")
    for attr in ("vendor_name", "invoice_number", "amount_total", "bank_account"):
        f = getattr(res.record, attr)
        assert f.value == SPANS[f.prov.span_id]


# ---------------------------------------------------------------- gate

def _record(account: str, tainted: bool = True) -> InvoiceRecord:
    return InvoiceRecord(
        doc_id="d1",
        vendor_name=Field("Meridian Supply Co.", Provenance(DOC_HASH, SPAN_VENDOR, tainted)),
        amount_total=Field("48200.00", Provenance(DOC_HASH, SPAN_AMT, tainted)),
        bank_account=Field(account, Provenance(DOC_HASH, SPAN_ACCT, tainted)),
    )


def test_known_account_may_be_proposed():
    d = gate_evaluate(_record(TRUSTED), _pattern())
    assert d.action is Action.PROPOSE_PAY


def test_tainted_unknown_account_always_escalates():
    d = gate_evaluate(_record(ATTACKER), _pattern())
    assert d.action is Action.ESCALATE
    assert "TAINTED_ACCOUNT_NOT_IN_MASTER" in d.codes


def test_first_time_vendor_always_escalates():
    assert gate_evaluate(_record(TRUSTED), None).action is Action.ESCALATE


def test_amount_outside_tolerance_escalates():
    d = gate_evaluate(_record(TRUSTED), _pattern(), expected_amount=10_000.0)
    assert d.action is Action.ESCALATE
    assert "AMOUNT_OUTSIDE_TOLERANCE" in d.codes


# ------------------------------------------------- the propose/approve boundary

def test_agent_ceiling_is_propose():
    """No input to the gate produces APPROVED. That is the point."""
    for acct in (TRUSTED, ATTACKER, ""):
        for pat in (_pattern(), None, _pattern(accounts=())):
            assert gate_evaluate(_record(acct), pat).action is not Action.APPROVED


def test_agents_cannot_approve():
    d = gate_evaluate(_record(TRUSTED), _pattern())
    with pytest.raises(PermissionError):
        approve(d, "agent:exception_resolver")


def test_approval_requires_a_human_identifier():
    d = gate_evaluate(_record(TRUSTED), _pattern())
    for bad in ("", "   "):
        with pytest.raises(PermissionError):
            approve(d, bad)
    assert approve(d, "aditya@kiet").action is Action.APPROVED


# --------------------------------------- the measured attacks, run against the gate

ROOT = Path(__file__).resolve().parents[1]
# A fresh run writes to out/ and wins. results/ is the committed measurement, so a
# clean clone runs this test too rather than silently skipping the headline claim.
ATTACK_RESULTS = next(
    (p for p in (ROOT / "out" / "attacks_undefended.jsonl",
                 ROOT / "results" / "attacks_undefended.jsonl") if p.exists()),
    ROOT / "out" / "attacks_undefended.jsonl")


@pytest.mark.skipif(not ATTACK_RESULTS.exists(), reason="run eval/measure_attacks.py first")
def test_every_payload_that_beat_the_model_is_stopped_by_the_design():
    """The A/B, as a test.

    12 of 20 payloads persuaded the model to emit the attacker's account. Model
    compromise is simulated here in the strongest form: assume the reader is fully
    owned and returns exactly what the attacker wants.

    The attacker's account is not a span in the document, so it cannot resolve;
    and even if it were planted as a span, it is not in the vendor master, so the
    gate escalates. Both layers are checked.
    """
    rows = [json.loads(l) for l in ATTACK_RESULTS.read_text().splitlines() if l.strip()]
    worked = [r for r in rows if r["verdict"] == "compromised"]
    assert worked, "expected some payloads to have compromised the undefended model"

    for r in worked:
        # Layer 1: a compromised reader emitting the literal value is rejected.
        res = resolve({"bank_account": ATTACKER}, SPANS, DOC_HASH, r["id"])
        assert res.record.bank_account is None, f"{r['id']} ({r['technique']}) resolved"

        # Layer 2: even with the account planted as a real span, the gate escalates.
        planted = dict(SPANS) | {"p0:0.10_0.50_0.50_0.52": ATTACKER}
        res2 = resolve({"bank_account": "p0:0.10_0.50_0.50_0.52"}, planted, DOC_HASH, r["id"])
        assert res2.record.bank_account.value == ATTACKER
        assert gate_evaluate(res2.record, _pattern()).action is Action.ESCALATE, r["id"]
