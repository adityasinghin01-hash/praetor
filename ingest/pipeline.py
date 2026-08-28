"""One PDF in, one decision out — the whole front door as a single callable.

`eval/run_pdf.py` proved this path by hand in Phase 2: a real file becomes spans through
Document AI, the quarantined reader answers with span ids, the resolver grounds them, the
canary checks where they came from, the rules compare against the supplier's history and
the gate has the last word. That logic lived inside a script's `main()`, which is fine
until something else needs it — and Phase 4 needs it on a Cloud Run instance woken by a
file landing in a bucket.

So it moved here, and the script calls it. **One implementation, two callers.** Two
copies of a pipeline are two pipelines, and the one that drifts is the one nobody is
watching (DECISIONS #15).

## Why this is not in praetor/

It orchestrates. It makes network calls, reads clocks, spends money and knows about
Document AI. The kernel's claim is that the security-critical path is small and
dependency-free, and that claim survives only if the convenient thing keeps living
outside it. `tests/test_ingest.py` asserts `praetor/` imports nothing from here.

## What it deliberately does NOT do

**It does not use Document AI's own field values.** `docai_adapter.to_record()` reads each
entity's `mentionText` and says so in its own docstring: it is a reference for scoring,
not how a value reaches a payment. Wiring that straight into the gate would automate the
pipeline by removing the guarantee the pipeline exists for. The record that reaches the
rules here is built by `praetor/resolver.py` from span ids and nothing else.

**It does not approve anything.** The ceiling is `PROPOSE_PAY`, as everywhere else. A
document arriving by itself, with no human in the loop, must not be able to end in a
payment — automation is allowed to prepare work for a person, never to replace them.

## Injection points, and why they are injected

`analyse` and `read` are parameters rather than imports so that the whole path can be
exercised on a saved Document AI response with no network, no credentials and no money —
which is what `tests/test_ingest.py` does, and it is the only way a test of this file can
run in CI.
"""
from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from praetor import baseline_rules, canary, costguard, docai_adapter
from praetor.gate import evaluate as gate_evaluate
from praetor.resolver import resolve
from praetor.types import Finding, InvoiceRecord, VendorPattern

PROJECT = "praetor-run-2026"
LOCATION = "asia-south1"
PROCESSOR = "8d5e7a53f2b61215"          # praetor-invoice-parser, pretrained-invoice-v1.3

# https://cloud.google.com/document-ai/pricing — Invoice Parser, per page. No free tier:
# every document through this pipeline costs money, which is the fact that makes
# `costguard` load-bearing here rather than decorative.
USD_PER_PAGE = 0.01


@dataclass
class Outcome:
    """What happened to one document. Serialisable, because it crosses a process."""
    doc_id: str
    doc_hash: str
    spans: int = 0
    pages: int = 0
    action: str = ""
    codes: list[str] = field(default_factory=list)
    canary_codes: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)
    extracted: dict[str, str | None] = field(default_factory=dict)
    seconds: float = 0.0
    usd: float = 0.0
    error: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def analyse_with_document_ai(pdf: bytes) -> dict:
    """Send one PDF to Document AI and return the parsed document.

    `urllib`, not a client library: `google.auth` already ships with `google-genai`, and
    adding a Document AI SDK to reach one endpoint would be a dependency for nothing.
    """
    import urllib.error
    import urllib.request

    url = (f"https://{LOCATION}-documentai.googleapis.com/v1/projects/{PROJECT}"
           f"/locations/{LOCATION}/processors/{PROCESSOR}:process")
    body = json.dumps({
        "rawDocument": {"content": base64.b64encode(pdf).decode(),
                        "mimeType": "application/pdf"},
        "skipHumanReview": True,
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["document"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Document AI refused this ({e.code}): "
            f"{e.read()[:300].decode('utf-8', 'replace')}") from e


def cached_analyser(path: str | Path) -> Callable[[bytes], dict]:
    """An `analyse` that reads a saved response. No network, no credentials, no charge."""
    document = json.loads(Path(path).read_text())
    return lambda _pdf: document


def process(
    pdf: bytes,
    doc_id: str,
    *,
    analyse: Callable[[bytes], dict] | None = None,
    read: Callable[[Mapping[str, str]], Mapping[str, object]] | None = None,
    pattern: VendorPattern | None = None,
    charge: bool = True,
) -> Outcome:
    """PDF bytes -> Document AI -> spans -> reader -> resolver -> canary -> rules -> gate.

    Returns an `Outcome` rather than raising, because the caller is usually an event
    handler: a document that cannot be processed must become a visible failed record, not
    a 500 that Eventarc retries forever.

    `read` is the quarantined reader. When it is None the pipeline stops after grounding
    and reports what Document AI found, which is honest about there being no extraction
    rather than quietly substituting Document AI's own values for the reader's.
    """
    started = time.time()
    out = Outcome(doc_id=doc_id, doc_hash="")

    # BEFORE the call, not after. A pipeline woken by a file landing in a bucket is a way
    # to spend money without a person deciding to, so anyone who can write to the bucket
    # can otherwise write to the bill. The page count is not known until the response
    # comes back, so one page is assumed here and the actual count is recorded below --
    # the same estimate-then-settle shape `costguard.check()` uses for tokens.
    if charge:
        try:
            costguard.check_pages(1, USD_PER_PAGE)
        except costguard.BudgetExceeded as e:
            out.error = f"budget: {e}"[:300]
            out.action = "escalate"
            out.codes = ["BUDGET_EXCEEDED"]
            out.seconds = time.time() - started
            return out

    try:
        document = (analyse or analyse_with_document_ai)(pdf)
    except Exception as e:  # noqa: BLE001
        out.error = f"document ai: {e}"[:300]
        out.action = "escalate"
        out.codes = ["INGEST_FAILED"]
        out.seconds = time.time() - started
        return out

    out.pages = len(document.get("pages") or [])
    if charge and out.pages:
        out.usd = out.pages * USD_PER_PAGE
        costguard.record_pages(out.pages, USD_PER_PAGE)

    # The document hash is over the parsed response, so the same PDF parsed twice grounds
    # against the same immutable document. Everything downstream cites it.
    out.doc_hash = "docai:" + docai_adapter.content_hash(document)
    spans = docai_adapter.spans_of(document)
    kinds = docai_adapter.span_kinds_of(document)
    out.spans = len(spans)

    if read is None:
        out.action = "escalate"
        out.codes = ["NO_READER"]
        out.seconds = time.time() - started
        return out

    try:
        mapping = read(spans)
    except Exception as e:  # noqa: BLE001
        out.error = f"reader: {e}"[:300]
        out.action = "escalate"
        out.codes = ["READER_FAILED"]
        out.seconds = time.time() - started
        return out

    # From here down there is no orchestration left -- it is the kernel, unchanged, and
    # exactly what tests/test_ingest.py runs directly to prove this file adds nothing.
    out.action, out.codes, out.canary_codes, out.refused, out.extracted = decide(
        dict(mapping), spans, kinds, out.doc_hash, doc_id, pattern)
    out.seconds = time.time() - started
    return out


def decide(mapping: dict, spans: dict[str, str], kinds: dict[str, str],
           doc_hash: str, doc_id: str, pattern: VendorPattern | None):
    """The kernel half, with nothing around it.

    Separated so a test can call it directly and compare, byte for byte, against what
    `process()` produces. If this function is the only place the two paths meet, "the
    automation changes nothing" stops being a claim about intent.
    """
    resolution = resolve(mapping, spans, doc_hash, doc_id)
    record: InvoiceRecord = resolution.record
    fired: list[Finding] = canary.check(record, kinds)
    rules = baseline_rules.evaluate(record, pattern)
    gate = gate_evaluate(record, pattern)
    codes = sorted({*rules.codes, *(f.code for f in fired), *gate.codes})
    extracted = {a: record.get(a) for a in (
        "vendor_name", "invoice_number", "amount_total", "currency",
        "bank_account", "tax_rate", "vendor_address")}
    return gate.action.value, codes, [f.code for f in fired], dict(resolution.rejected), extracted
