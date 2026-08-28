"""The automation layer adds nothing to the kernel, and removes nothing from it.

`docs/PLAN.md` Phase 4 puts one condition on automating the pipeline: **the kernel gets
no automation dependency, and a test proves it runs identically with the whole layer
switched off.** That sentence is the reason this file exists, and the two tests that
carry it are `test_the_kernel_does_not_know_ingest_exists` and
`test_the_pipeline_decides_exactly_what_the_kernel_decides`.

Everything here runs on a saved Document AI response: no network, no credentials, no
money. A test of an ingestion pipeline that can only run against live infrastructure is
a test that does not run.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from ingest import pipeline
from praetor import costguard, docai_adapter

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "docai_V000_003.json"


@pytest.fixture
def document():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def analyse():
    return pipeline.cached_analyser(FIXTURE)


def _reader_for(document):
    """A reader that answers with the real span ids, so the kernel gets a valid answer.

    Deliberately not a model. What is being tested is the plumbing around the kernel, and
    a test whose result depends on what a model felt like saying is not a test.
    """
    kinds = docai_adapter.span_kinds_of(document)
    mapping = {}
    for attr, kind in (("bank_account", "payment_iban"), ("invoice_number", "invoice_id"),
                       ("amount_total", "total_amount"), ("currency", "currency")):
        sid = next((s for s, k in kinds.items() if k == kind), None)
        if sid:
            mapping[attr] = sid
    return lambda spans: mapping


# --------------------------------------------------------------- the Phase 4 condition

def test_the_kernel_does_not_know_ingest_exists():
    """The dependency runs one way. If it ever ran both, 'switch the layer off' would
    stop being a thing anybody could do."""
    offenders = []
    for path in sorted((ROOT / "praetor").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            if "ingest" in names:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, f"praetor/ imports the automation layer: {offenders}"


def test_the_kernel_runs_with_the_automation_layer_uninstalled(monkeypatch):
    """Not 'ingest is unused' -- 'ingest is absent'.

    `ingest` is evicted from `sys.modules` and made unimportable, then a document is put
    through the kernel. If anything in `praetor/` had grown a lazy import of the
    automation layer, this is where it would surface.
    """
    document = json.loads(FIXTURE.read_text())
    for name in [m for m in sys.modules if m == "ingest" or m.startswith("ingest.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def blocked(name, *a, **k):
        if name == "ingest" or name.startswith("ingest."):
            raise ImportError("the automation layer is switched off for this test")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", blocked)

    from praetor import baseline_rules, canary
    from praetor.gate import evaluate as gate_evaluate
    from praetor.resolver import resolve

    spans = docai_adapter.spans_of(document)
    kinds = docai_adapter.span_kinds_of(document)
    res = resolve(_reader_for(document)(spans), spans, "docai:x", "V000_003")
    assert res.record.bank_account is not None
    assert canary.check(res.record, kinds) == []
    assert baseline_rules.evaluate(res.record, None).codes
    assert gate_evaluate(res.record, None).action.value == "escalate"


def test_the_pipeline_decides_exactly_what_the_kernel_decides(document, analyse):
    """The automation is a courier. Same document, same answer, field for field.

    `pipeline.decide()` is the kernel half with no orchestration around it. Running it
    directly and running the whole pipeline must agree on every field of the outcome --
    otherwise 'the automation changes nothing' is a claim about intent rather than a fact
    about behaviour.
    """
    read = _reader_for(document)
    spans = docai_adapter.spans_of(document)
    kinds = docai_adapter.span_kinds_of(document)
    doc_hash = "docai:" + docai_adapter.content_hash(document)

    direct = pipeline.decide(dict(read(spans)), spans, kinds, doc_hash, "V000_003", None)
    through = pipeline.process(b"", "V000_003", analyse=analyse, read=read, charge=False)

    assert (through.action, through.codes, through.canary_codes, through.refused,
            through.extracted) == direct
    assert through.doc_hash == doc_hash


# ------------------------------------------------------------------- what it may not do

def test_automation_can_never_end_in_a_payment(document, analyse):
    """A document that arrives by itself, with nobody watching, must not be payable.

    The gate's ceiling is PROPOSE_PAY everywhere else; automation is allowed to prepare
    work for a person, never to replace them.
    """
    out = pipeline.process(b"", "V000_003", analyse=analyse,
                           read=_reader_for(document), charge=False)
    assert out.action != "approved"
    assert out.action in ("escalate", "propose_pay")


def test_no_reader_is_an_escalation_not_a_substitution(document, analyse):
    """Document AI's own field values must never stand in for the reader's answer.

    `docai_adapter.to_record()` reads each entity's `mentionText`, and says in its own
    docstring that it is a reference for scoring rather than how a value reaches a
    payment. Wiring it into the gate would automate the pipeline by deleting the
    guarantee the pipeline exists for.
    """
    out = pipeline.process(b"", "V000_003", analyse=analyse, read=None, charge=False)
    assert out.action == "escalate"
    assert out.codes == ["NO_READER"]
    assert not out.extracted, "no reader means no extracted values, not Document AI's"


def test_a_broken_document_becomes_a_record_not_an_exception(analyse):
    """The caller is an event handler. A document that cannot be processed must become a
    visible failed record, not a 500 that the trigger retries forever."""
    def explode(_pdf):
        raise RuntimeError("Document AI refused this (400)")

    out = pipeline.process(b"", "V000_003", analyse=explode, charge=False)
    assert out.action == "escalate"
    assert out.codes == ["INGEST_FAILED"]
    assert "Document AI refused" in out.error


def test_a_failing_reader_escalates_rather_than_passing_the_document(document, analyse):
    def explode(_spans):
        raise RuntimeError("model unavailable")

    out = pipeline.process(b"", "V000_003", analyse=analyse, read=explode, charge=False)
    assert out.action == "escalate"
    assert out.codes == ["READER_FAILED"]


# ------------------------------------------------------------------------- the spending

def test_the_budget_is_checked_before_document_ai_is_called(document, monkeypatch):
    """Anyone who can write to the bucket can otherwise write to the bill.

    The ceiling has to refuse the call, not report it afterwards -- so this asserts
    Document AI was never reached, rather than that the outcome mentions money.
    """
    monkeypatch.setattr(costguard, "CEILING_INR", 0.0)
    called = []

    def analyse(_pdf):
        called.append(1)
        return json.loads(FIXTURE.read_text())

    out = pipeline.process(b"", "V000_003", analyse=analyse, charge=True)
    assert called == [], "Document AI was called despite the ceiling being exhausted"
    assert out.codes == ["BUDGET_EXCEEDED"]
    assert out.action == "escalate"


def test_pages_are_recorded_on_the_same_ledger_as_tokens():
    """Two ledgers with two ceilings is two ways to be under budget while over it."""
    before = costguard._load()
    costguard.record_pages(3, 0.01)
    after = costguard._load()
    assert after.pages == before.pages + 3
    assert after.usd == pytest.approx(before.usd + 0.03)


# ---------------------------------------------------------------------------
# The service. Two of these pin bugs that were measured costing money on the first
# deployment, so they are worth more than their size suggests.

def test_no_response_is_sent_without_a_body():
    """A Content-Length with no body made Cloud Run return 502.

    Eventarc treats a 502 as a failure and redelivers. Every redelivery re-ran Document
    AI, so one invoice was billed nine times before anyone looked at the status codes --
    the handler's own log said 204 while the platform was returning 502. A response the
    platform cannot parse is not a cosmetic bug when the retry costs a penny a page.

    The bug was a body write sitting behind an `if`, so that is what this reads.
    """
    import ast
    import inspect
    import textwrap

    from ingest import server

    tree = ast.parse(textwrap.dedent(inspect.getsource(server.Handler._done)))
    writes = [n for n in ast.walk(tree)
              if isinstance(n, ast.Attribute) and n.attr == "write"]
    assert writes, "the response body is never written"
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            assert not any(isinstance(x, ast.Attribute) and x.attr == "write"
                           for x in ast.walk(node)), \
                "the body write is conditional again; that is what caused the 502"


def test_a_status_that_makes_eventarc_retry_is_never_returned():
    """204 forbids a body, and this handler always sends one. Any 2xx acks the event."""
    import inspect
    import re

    from ingest import server

    source = inspect.getsource(server.Handler)
    code = re.sub(r'""".*?"""', "", source, flags=re.S)
    code = "\n".join(l for l in code.splitlines() if not l.strip().startswith("#"))
    assert "_done(204" not in code and "send_response(204)" not in code


def test_an_already_claimed_object_is_not_processed_again(monkeypatch):
    """At-least-once delivery makes a duplicate delivery a duplicate charge.

    The 502 was a bug and is fixed; redelivery is not a bug, it is the platform's
    contract. So the claim is what actually protects the bill, and it must be checked
    before anything is fetched or parsed.
    """
    from ingest import server

    touched = []
    monkeypatch.setattr(server, "claim", lambda *a: False)
    monkeypatch.setattr(server, "fetch", lambda *a: touched.append("fetch") or b"")
    monkeypatch.setattr(server, "store_outcome", lambda *a: touched.append("store"))

    assert server.handle({"bucket": "b", "name": "x.pdf", "generation": "1"}) is None
    assert touched == [], "a redelivered event reached the paid path"


def test_a_fresh_object_is_processed(monkeypatch):
    """The counterpart, so the test above cannot pass by refusing everything."""
    from ingest import server

    stored = []
    monkeypatch.setattr(server, "claim", lambda *a: True)
    monkeypatch.setattr(server, "fetch", lambda *a: b"%PDF-")
    monkeypatch.setattr(server, "store_outcome", lambda *a: stored.append(a[0]))
    monkeypatch.setattr(server, "reader", lambda: None)
    monkeypatch.setattr(server.pipeline, "process",
                        lambda pdf, doc_id, **k: server.pipeline.Outcome(
                            doc_id=doc_id, doc_hash="h", action="escalate"))

    out = server.handle({"bucket": "b", "name": "V9.pdf", "generation": "1"})
    assert out is not None and out.doc_id == "V9"
    assert len(stored) == 1


def test_the_claim_is_written_before_the_money_is_spent(monkeypatch):
    """Order matters and is easy to get backwards.

    A crash after claiming loses a document, which a person can see and re-upload. A
    crash before claiming charges twice, which nobody sees.
    """
    from ingest import server

    order = []
    monkeypatch.setattr(server, "claim", lambda *a: order.append("claim") or True)
    monkeypatch.setattr(server, "fetch", lambda *a: order.append("fetch") or b"")
    monkeypatch.setattr(server, "reader", lambda: None)
    monkeypatch.setattr(server.pipeline, "process",
                        lambda pdf, doc_id, **k: order.append("document-ai")
                        or server.pipeline.Outcome(doc_id=doc_id, doc_hash="h"))
    monkeypatch.setattr(server, "store_outcome", lambda *a: order.append("store"))

    server.handle({"bucket": "b", "name": "V9.pdf", "generation": "1"})
    assert order.index("claim") < order.index("document-ai")


def test_the_service_refuses_to_start_without_a_durable_ledger(monkeypatch):
    """A ceiling that resets on every cold start is not a ceiling.

    Measured: the same spend reads as Rs 2.64 through Firestore and Rs 0.00 through the
    file backend after a restart, because a container filesystem is ephemeral.
    """
    import pytest as _pytest

    from ingest import ledger, server

    monkeypatch.setattr(ledger, "install", lambda *a, **k: False)
    with _pytest.raises(SystemExit) as excinfo:
        server.main()
    assert "REFUSING TO START" in str(excinfo.value)
