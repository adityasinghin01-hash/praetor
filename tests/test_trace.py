"""Tracing, expressed as tests.

The architecture has claimed since its first draft that spans carry taint labels
throughout. These pin that claim, and pin the two things that must stay true of it:
tracing is off unless asked for, and a missing tracer never changes an outcome.
"""
import pytest

from praetor import trace
from praetor.gate import Action, approve, evaluate
from praetor.resolver import resolve
from praetor.types import Field, InvoiceRecord, Provenance, VendorPattern

TRUSTED = "IN45-HDFC-0001-7788"
ATTACKER = "IN99-XXXX-6666-0001"
SPANS = {
    "p0:0.10_0.10_0.40_0.12": "Meridian Supply Co.",
    "p0:0.10_0.40_0.50_0.42": TRUSTED,
}
SPAN_VENDOR, SPAN_ACCT = SPANS.keys()


@pytest.fixture
def traced(tmp_path, monkeypatch):
    """Tracing on, exporting to a temp file."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("PRAETOR_TRACE", "1")
    monkeypatch.setattr(trace, "TRACE_FILE", path)
    trace.configure(path, force=True)
    return path


def _record(account=TRUSTED, tainted=True, tenant=None):
    return InvoiceRecord(
        doc_id="d1", tenant_id=tenant,
        vendor_name=Field("Meridian Supply Co.", Provenance("abc123", SPAN_VENDOR, tainted)),
        bank_account=Field(account, Provenance("abc123", SPAN_ACCT, tainted)),
    )


# ---------------------------------------------------------------- off by default

def test_tracing_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("PRAETOR_TRACE", raising=False)
    assert not trace.enabled()


def test_a_span_with_tracing_off_changes_nothing(monkeypatch):
    monkeypatch.delenv("PRAETOR_TRACE", raising=False)
    with trace.span("anything", **{"praetor.x": 1}) as s:
        s.set_attribute("praetor.y", 2)      # must not raise


def test_the_pipeline_works_with_tracing_off(monkeypatch):
    monkeypatch.delenv("PRAETOR_TRACE", raising=False)
    res = resolve({"bank_account": SPAN_ACCT}, SPANS, "abc123", "d1")
    assert res.record.bank_account.value == TRUSTED


# ---------------------------------------------------------------- taint on spans

@pytest.mark.skipif(not trace.AVAILABLE, reason="opentelemetry not installed")
def test_the_gate_records_whether_the_account_was_tainted(traced):
    evaluate(_record(ATTACKER), VendorPattern(vendor_key="v", n_invoices=9,
                                              bank_accounts={TRUSTED}))
    spans = [s for s in trace.read(traced) if s["name"] == "gate.evaluate"]
    assert spans
    a = spans[-1]["attributes"]
    assert a["praetor.account.tainted"] is True
    assert a["praetor.account.span_id"] == SPAN_ACCT
    assert a["praetor.account.doc_hash"] == "abc123"
    assert a["praetor.action"] == Action.ESCALATE.value
    assert "TAINTED_ACCOUNT_NOT_IN_MASTER" in a["praetor.findings"]


@pytest.mark.skipif(not trace.AVAILABLE, reason="opentelemetry not installed")
def test_a_clean_account_traces_as_proposed(traced):
    evaluate(_record(TRUSTED), VendorPattern(vendor_key="v", n_invoices=9,
                                             bank_accounts={TRUSTED}))
    a = [s for s in trace.read(traced) if s["name"] == "gate.evaluate"][-1]["attributes"]
    assert a["praetor.action"] == Action.PROPOSE_PAY.value
    assert a["praetor.findings"] == ""


@pytest.mark.skipif(not trace.AVAILABLE, reason="opentelemetry not installed")
def test_resolution_records_what_was_rejected(traced):
    """A model handing back a literal instead of a reference should be findable later."""
    resolve({"bank_account": ATTACKER}, SPANS, "abc123", "d1")
    a = [s for s in trace.read(traced) if s["name"] == "resolve"][-1]["attributes"]
    assert a["praetor.fields_rejected"] == 1
    assert a["praetor.fields_resolved"] == 0
    assert "not a span reference" in a["praetor.rejected"]


@pytest.mark.skipif(not trace.AVAILABLE, reason="opentelemetry not installed")
def test_approval_traces_as_declassification(traced):
    d = evaluate(_record(ATTACKER), VendorPattern(vendor_key="v", n_invoices=9))
    approve(d, "aditya@kiet")
    a = [s for s in trace.read(traced) if s["name"] == "gate.approve"][-1]["attributes"]
    assert a["praetor.approved_by"] == "aditya@kiet"
    assert a["praetor.declassified"] is True


@pytest.mark.skipif(not trace.AVAILABLE, reason="opentelemetry not installed")
def test_a_refused_approval_leaves_no_declassification_span(traced):
    """An agent's attempt must not appear as though it succeeded."""
    d = evaluate(_record(TRUSTED), VendorPattern(vendor_key="v", n_invoices=9,
                                                 bank_accounts={TRUSTED}))
    with pytest.raises(PermissionError):
        approve(d, "agent:exception_resolver")
    assert [s for s in trace.read(traced) if s["name"] == "gate.approve"] == []


# ---------------------------------------------------------------- the helper

def test_taint_describes_a_tainted_field():
    f = Field(TRUSTED, Provenance("abc123", SPAN_ACCT, True))
    a = trace.taint(f)
    assert a["praetor.tainted"] is True
    assert a["praetor.doc_hash"] == "abc123"


def test_taint_of_a_missing_field_says_so():
    assert trace.taint(None) == {"praetor.present": False}
