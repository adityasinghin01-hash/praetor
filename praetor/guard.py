"""A drop-in guard for any model that reads an untrusted document.

This is PRAETOR's security kernel with the invoices taken out. It knows nothing about
suppliers, bank accounts, purchase orders or tax rates. It knows one thing:

    **A model may point at a value. It may not author one.**

Give it the spans of a document and a function that calls your model. It returns values
that provably came out of the document, plus an explicit refusal for everything else.
There is no configuration under which it returns a string the model made up, because it
never uses the model's output as a value — only as a key.

    guard = Guard(spans, doc_hash="sha256:...")
    result = guard.run(my_model_reader)

    result.values    # {"recipient": Grounded(value=..., origin=...)}
    result.refused   # {"amount": "not a span reference: '£4,200.00'"}

Why this file exists separately. The claim PRAETOR makes is that the security-critical
path is small, dependency-free and checkable by anyone. That claim is much easier to
believe about 150 lines with no domain in them than about a file that also knows what a
tax rate is. `praetor/resolver.py` and `praetor/canary.py` are now thin adapters over
this, so there is one implementation of the mechanism rather than two that can drift.

**Standard library only, and permanently so.** `tests/test_guard.py` asserts it. The
security argument stays checkable with nothing installed but pytest.

## The two things it does

**Grounding.** A reader's answer is a span id. The guard looks it up. Anything that is
not a span id, or is a span id that is not in this document, is refused and never
becomes a value. This is the guarantee.

**Origin policy, optional.** Grounding proves a value is *in* the document. It says
nothing about *where*, and an attacker who controls the document chooses where. If you
can say which kinds of span a field may legitimately come from, the guard enforces it —
by reading the document's own label for the span, never the span's text. Nothing an
attacker writes is an input to that decision.

## What it does not do

It does not stop a reader pointing at the wrong span. That is not an oversight; a wrong
pointer still yields a value that is genuinely in the document, and deciding whether it
should be *acted on* needs domain knowledge this file deliberately does not have. Put a
policy layer above it. `praetor/gate.py` is one.

It has no opinion about prompts, models or providers, and it never sees the model's
prompt. It is not a filter and does not try to detect anything.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

__all__ = ["SPAN_ID_RE", "Grounded", "Guard", "Origin", "OriginViolation", "Result",
           "is_reference", "check_origins"]

# A reference is a span id: page, then the span's coordinates. The exact shape is the
# document adapter's business -- the guard only needs it to be recognisable and to be
# something a model cannot accidentally produce a *valid* one of by writing prose.
SPAN_ID_RE = re.compile(r"^p\d+:[0-9._]+$")


def is_reference(value: object) -> bool:
    """True if this looks like a span reference rather than content."""
    return isinstance(value, str) and bool(SPAN_ID_RE.match(value.strip()))


@dataclass(frozen=True)
class Origin:
    """Where a grounded value came from. Rides with the value everywhere it goes."""
    doc_hash: str
    span_id: str
    kind: str | None = None      # the document's own label for this span, if known
    tainted: bool = True         # it came off an untrusted document; it stays true


@dataclass(frozen=True)
class Grounded:
    """A value that provably came out of the document, and the pointer that proves it."""
    value: str
    origin: Origin

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OriginViolation:
    """A grounded value that arrived from somewhere it could not have come from.

    `reason` is structured rather than prose so callers can map it onto their own
    vocabulary without matching on a sentence that might get reworded.
    """
    field: str
    reason: str          # "unknown_origin" | "origin_not_permitted"
    detail: str


@dataclass
class Result:
    values: dict[str, Grounded] = field(default_factory=dict)
    refused: dict[str, str] = field(default_factory=dict)     # field -> why
    violations: dict[str, OriginViolation] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.refused and not self.violations

    def get(self, name: str) -> str | None:
        g = self.values.get(name)
        return g.value if g is not None else None


def check_origins(values: Mapping[str, Grounded],
                  allowed: Mapping[str, Iterable[str]]) -> dict[str, OriginViolation]:
    """Which grounded values arrived from somewhere they could not legitimately come from.

    Reads the span's *label*, never its text. A field with no entry in `allowed` is not
    constrained. A constrained field whose origin kind is unknown is a violation, because
    "we could not establish where this came from" must not read the same as "fine".
    """
    out: dict[str, OriginViolation] = {}
    for name, grounded in values.items():
        if name not in allowed:
            continue
        permitted = {str(k) for k in allowed[name]}
        kind = grounded.origin.kind
        if not kind:
            out[name] = OriginViolation(
                name, "unknown_origin",
                f"{name} came from span {grounded.origin.span_id}, whose kind is "
                f"not known")
        elif kind not in permitted:
            out[name] = OriginViolation(
                name, "origin_not_permitted",
                f"{name} came from a {kind!r} span; it can legitimately come from "
                f"{' or '.join(sorted(permitted))}")
    return out


class Guard:
    """One document, held immutably, plus the rules for getting values out of it."""

    def __init__(self, spans: Mapping[str, str], doc_hash: str, doc_id: str = "",
                 span_kinds: Mapping[str, str] | None = None,
                 allowed_origins: Mapping[str, Iterable[str]] | None = None) -> None:
        # Copied, not referenced. The document a value is checked against must not be
        # something a caller can still be holding a mutable handle to.
        self._spans = dict(spans)
        self._kinds = dict(span_kinds or {})
        self._allowed = {k: frozenset(str(x) for x in v)
                         for k, v in (allowed_origins or {}).items()}
        self.doc_hash = doc_hash
        self.doc_id = doc_id

    @property
    def spans(self) -> dict[str, str]:
        """What the reader is shown: span id -> text. A copy, for the same reason."""
        return dict(self._spans)

    def ground(self, reader_output: Mapping[str, object]) -> Result:
        """Turn {field: span_id} into grounded values, refusing anything else.

        `None` and empty answers mean "not found" and are simply absent from the result,
        which is different from being refused and should stay different: one is the model
        declining, the other is the model trying something it is not allowed to do.
        """
        result = Result()
        for name, raw in reader_output.items():
            if raw is None:
                continue
            ref = str(raw).strip()
            if not ref:
                continue
            if not is_reference(ref):
                # The model answered with content where a pointer was required. This is
                # the exact failure an injected document is trying to cause.
                result.refused[name] = f"not a span reference: {ref[:40]!r}"
                continue
            if ref not in self._spans:
                result.refused[name] = f"span not present in document: {ref}"
                continue
            result.values[name] = Grounded(
                value=self._spans[ref],
                origin=Origin(doc_hash=self.doc_hash, span_id=ref,
                              kind=self._kinds.get(ref)),
            )

        if self._allowed:
            result.violations = check_origins(result.values, self._allowed)
        return result

    def run(self, read: Callable[[Mapping[str, str]], Mapping[str, object]]) -> Result:
        """Show the reader the spans, ground whatever comes back.

        The reader is handed a copy and its return value is treated as untrusted input,
        which is the entire contract. A reader that raises is the caller's problem; a
        reader that lies is this file's problem, and is handled.
        """
        return self.ground(read(self.spans))
