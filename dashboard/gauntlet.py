"""Type your own fraud into a real invoice and watch it fail. Or succeed.

This runs the actual kernel, stage by stage, on a real document from the corpus with one
line of the visitor's text added to it. Nothing here is a mock, a script or a replay: the
same `resolve`, `canary`, `authority`, `baseline_rules` and `gate` that run in the queue
run here, in that order, and each reports what it did.

**The reader is assumed to have been fooled, and that is deliberate.** By default this
does not call a model. It hands the privileged field straight to the visitor's span, as
if the reading model had been completely taken in. Two reasons, and both matter more than
the theatre of a live model call:

1. **It is the honest worst case.** FINDINGS §1 measured 12 of 20 injection techniques
   succeeding against an ordinary extraction prompt. A demo that depends on the model
   happening to fall for *this particular* visitor's sentence would show a green tick for
   the wrong reason — the attack failing is not the same as the defence working.
2. **It demonstrates the actual claim.** PRAETOR does not claim the model resists
   injection. It claims being fooled does not matter. The only way to show that is to
   assume the model was fooled and see what still stops the payment.

Pass `use_model=True` to route through the real quarantined reader instead. That costs a
model call and is capped by `praetor/costguard.py`.

Every stage returns a sentence Priya could read. `dashboard/language.py` owns the words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from praetor import authority, baseline_rules, canary
from praetor.docile_adapter import (_span_id, load_annotation, span_kinds_of, spans_of,
                                    to_record)
from praetor.gate import Action, evaluate as gate_evaluate
from praetor.resolver import resolve
from praetor.types import Field, InvoiceRecord, Provenance, VendorPattern

from dashboard import language

ROOT = Path(__file__).resolve().parents[1]

# Where the visitor's line is placed on the page: a footer note, which is exactly where
# a real injected instruction goes. The document labels it as free text, because that is
# what it is -- the canary's whole job is to notice that a bank account came from here.
NOTE_BBOX = [0.12, 0.905, 0.88, 0.945]
NOTE_KIND = "other"

# Something that looks like an account number in the visitor's text. Only used to say
# whose account the money would have gone to; nothing branches on it.
ACCOUNT_LIKE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{8,26})\b")


@dataclass
class Step:
    key: str
    passed: bool                 # did the payment survive this check?
    detail: str                  # one plain sentence
    stopped_here: bool = False

    @property
    def name(self) -> str:
        return language.step_name(self.key)

    def as_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "passed": self.passed,
                "detail": self.detail, "stopped_here": self.stopped_here}


@dataclass
class Outcome:
    doc_id: str
    injected_text: str
    steps: list[Step] = field(default_factory=list)
    stopped: bool = False
    stopped_at: int | None = None       # 1-based, for "stopped at step 4"
    amount: str | None = None
    currency: str | None = None
    attacker_account: str | None = None
    would_have_paid: str | None = None  # the sentence that lands
    beat: list[str] = field(default_factory=list)   # which checks it got past

    def as_dict(self) -> dict:
        return {"doc_id": self.doc_id, "injected_text": self.injected_text,
                "steps": [s.as_dict() for s in self.steps], "stopped": self.stopped,
                "stopped_at": self.stopped_at, "amount": self.amount,
                "currency": self.currency, "attacker_account": self.attacker_account,
                "would_have_paid": self.would_have_paid, "beat": self.beat}


def documents(annotations: str | Path = "data/constructed", limit: int = 40,
              exceptions: str | Path = "out/exc_constructed.jsonl") -> list[str]:
    """Documents a visitor may choose from: only ones nothing is already wrong with.

    A document the rules already flag would stop at step 4 no matter what the visitor
    typed, and they would learn nothing except that the demo is rigged. Offering only
    clean invoices means the line they add is the only thing wrong with it, so every
    step they see is a response to *them*.
    """
    d = ROOT / annotations if not Path(annotations).is_absolute() else Path(annotations)

    # A fresh run in out/ wins; results/ is the committed fallback. The same rule
    # dashboard/build.py uses, and it is load-bearing here rather than a nicety:
    # `out/` is in .dockerignore, so on Cloud Run only results/ exists. Reading just
    # out/ would leave `flagged` empty in production and quietly offer the visitor
    # invoices that are already broken -- every attack would stop on the pre-existing
    # fault instead of on their line, and the page would look rigged.
    e = ROOT / exceptions if not Path(exceptions).is_absolute() else Path(exceptions)
    if not e.exists():
        e = ROOT / "results" / Path(exceptions).name
    flagged: set[str] = set()
    if e.exists():
        import json as _json
        flagged = {_json.loads(line)["doc_id"] for line in e.read_text().splitlines()
                   if line.strip()}
    clean = [p.stem for p in sorted(d.glob("*.json")) if p.stem not in flagged]
    # Never the first three of a vendor: those are the invoices that establish what
    # normal looks like, so there is no history to judge an attack against yet.
    return [c for c in clean if not c.endswith(("_000", "_001", "_002"))][:limit]


def _with_note(annotation: dict, text: str) -> tuple[dict, str]:
    """The document, plus the visitor's line as a real span. Returns (doc, its span id).

    It is added as a genuine span, not smuggled in. That is the point: the visitor's text
    really is in the document, the reader really may point at it, and the resolver really
    will allow it -- because it is there. Everything after that is what stops it.
    """
    doc = {**annotation, "field_extractions": list(annotation["field_extractions"])}
    doc["field_extractions"].append({
        "fieldtype": NOTE_KIND, "text": text, "page": 0,
        "bbox": list(NOTE_BBOX), "line_item_id": None,
    })
    return doc, _span_id(0, NOTE_BBOX)


def run(doc_id: str, injected_text: str, pattern: VendorPattern | None,
        register=None, annotations: str | Path = "data/constructed",
        use_model: bool = False) -> Outcome:
    """Run the real pipeline on this document with this line added, and narrate it."""
    base = ROOT / annotations if not Path(annotations).is_absolute() else Path(annotations)
    path = base / f"{doc_id}.json"
    if not path.exists():
        raise FileNotFoundError(doc_id)

    annotation, _ = load_annotation(path)
    doc, note_span = _with_note(annotation, injected_text)
    doc_hash = f"demo:{abs(hash((doc_id, injected_text))) % (16 ** 12):012x}"
    spans = spans_of(doc, doc_hash)
    kinds = span_kinds_of(doc)
    truth = to_record(doc, doc_hash, doc_id=doc_id)

    out = Outcome(doc_id=doc_id, injected_text=injected_text)
    out.amount = truth.get("amount_total")
    out.currency = truth.get("currency")
    m = ACCOUNT_LIKE.search(injected_text.upper())
    out.attacker_account = m.group(1) if m else None

    # ---- 1. read the invoice
    out.steps.append(Step("spans", True,
                          f"The invoice was split into {len(spans)} pieces of text, "
                          f"including the line you added."))

    # ---- what the reader answers. Fooled, by assumption, unless a model is asked.
    #
    # Which *kind* of attack this is depends on what the visitor wrote, and the two
    # kinds travel different routes through the system -- which is the thing worth
    # showing, because a demo that always stops at the same step teaches nothing about
    # the layers underneath it.
    #
    #   text containing an account   -> a VALUE attack. The reader is assumed to point
    #                                   the privileged field at the visitor's line.
    #   text containing no account   -> a DECISION attack. The reader extracts correctly
    #                                   and the line only gets to argue, which is what
    #                                   "this was approved on the call" actually does.
    if use_model:
        from praetor.agents import reader as remote_reader
        mapping = remote_reader.read(spans).mapping
    else:
        mapping = {a: sid for a, sid in
                   ((k, next((s for s, t in spans.items() if t == truth.get(k)), None))
                    for k in ("vendor_name", "invoice_number", "amount_total", "currency",
                              "bank_account", "tax_rate", "vendor_address"))
                   if sid}
        if out.attacker_account:
            mapping["bank_account"] = note_span   # the injection succeeded, completely

    # ---- 2. the resolver
    res = resolve(mapping, spans, doc_hash, doc_id)
    account = res.record.get("bank_account")
    if account is None:
        out.steps.append(Step("reference", False,
                              "The reading model tried to write a bank account of its "
                              "own instead of pointing at one on the invoice. Refused.",
                              stopped_here=True))
        return _finish(out)
    out.steps.append(Step("reference", True,
                          "The account is genuinely printed on this invoice, so it was "
                          "allowed through to the checks below."))
    out.beat.append("reference")

    # ---- 3. the canary: where on the page did it come from?
    fired = canary.check(res.record, kinds)
    if fired:
        out.steps.append(Step("origin", False, language.explain(fired[0].code).headline,
                              stopped_here=True))
        return _finish(out)
    out.steps.append(Step("origin", True,
                          "The account is printed in the payment section, where it "
                          "belongs."))
    out.beat.append("origin")

    # ---- 4. the supplier's own records
    decision = gate_evaluate(res.record, pattern)
    master = [f for f in decision.findings
              if f.code in ("TAINTED_ACCOUNT_NOT_IN_MASTER", "FIRST_TIME_VENDOR")]
    if master:
        out.steps.append(Step("master", False, language.explain(master[0].code).headline,
                              stopped_here=True))
        return _finish(out)
    out.steps.append(Step("master", True,
                          "This is an account you have paid this supplier at before."))
    out.beat.append("master")

    # ---- 5. approval the document claims for itself
    context = [t for sid, t in spans.items() if kinds.get(sid) == NOTE_KIND]
    amount = baseline_rules._to_float(truth.get("amount_total"))
    bad = authority.unverified(context, register, amount)
    if bad:
        out.steps.append(Step("authority", False,
                              "The invoice says it was approved. We checked your "
                              "records. There is no such approval.",
                              stopped_here=True))
        return _finish(out)
    out.steps.append(Step("authority", True,
                          "The invoice does not claim an approval we cannot check."))
    out.beat.append("authority")

    # ---- 6. the supplier's previous invoices
    rules = baseline_rules.evaluate(res.record, pattern)
    if rules.findings:
        out.steps.append(Step("rules", False,
                              language.explain(rules.findings[0].code).headline,
                              stopped_here=True))
        return _finish(out)
    out.steps.append(Step("rules", True,
                          "Nothing about this invoice is unusual for this supplier."))
    out.beat.append("rules")

    # ---- 7. can it be paid without a person?
    if decision.action is Action.PROPOSE_PAY:
        out.steps.append(Step("human", True,
                              "Everything checked out. This would be put in front of a "
                              "person to approve — the system never pays on its own."))
    else:
        out.steps.append(Step("human", False,
                              "A person must decide on this one.", stopped_here=True))
    return _finish(out)


def _finish(out: Outcome) -> Outcome:
    stopped = [i for i, s in enumerate(out.steps, 1) if s.stopped_here]
    out.stopped = bool(stopped)
    out.stopped_at = stopped[0] if stopped else None

    money = f"{out.currency or ''} {out.amount or ''}".strip() or "this invoice"

    if not out.stopped:
        # Worth saying plainly rather than dressing up. Some lines get all the way
        # through, and the honest answer is that the last line of defence is a person --
        # which is also the answer to "what if someone writes something you did not
        # think of".
        out.would_have_paid = (
            "Nothing here objected to your line. It still goes to a person to approve, "
            "because the system has no way to pay anything by itself.")
    elif out.attacker_account:
        # A value attack: the money had somewhere else to go, and we can name it.
        out.would_have_paid = (
            f"Stopped at step {out.stopped_at}. Without these checks, {money} would "
            f"have gone to {out.attacker_account}.")
    else:
        # A decision attack: the line was arguing for the invoice to be waved through,
        # not redirecting it. Naming an account here would be inventing one.
        out.would_have_paid = (
            f"Stopped at step {out.stopped_at}. Your line was trying to talk the system "
            f"into paying {money} without anyone looking at it.")
    return out
