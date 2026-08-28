"""Two paths must agree, or a person looks.

`praetor/guard.py` guarantees a value came out of the document. `praetor/canary.py`
guarantees it came from a place that field can legitimately live. Neither says anything
about the case in the middle: a value that is genuinely on the page, in a plausible
place, and still the attacker's -- because the model was persuaded to point at it.

The answer here is not a better model. It is a second opinion that **cannot be persuaded
by the same means**, and a rule that a disagreement is not resolved by picking a winner.

    outcome = corroborate(path_a_span, path_b)
    outcome.agreed       # both paths named the same span
    outcome.code         # "" | PATHS_DISAGREE | NO_SECOND_OPINION | ...

## Why two paths and not two models

Two models are one mechanism. FINDINGS §2 measured which injections beat an extraction
prompt, and the split was total: the twelve that worked read like ordinary business
correspondence. Anything that works by reading is movable by that class of sentence, so a
second reader -- a bigger model, a different vendor, a self-critique pass -- fails
correlated with the first. Adding it raises the cost of an attack without bounding it,
which is DECISIONS #2's whole argument.

Path B (`praetor/pathb.py`) reads geometry, character ratios and checksums. It has no
access to meaning, so the sentence that moves Path A is not an input to it. That is the
only property that makes the second opinion worth having, and it is a property of the
mechanism rather than of its accuracy.

## What agreement is and is not

Agreement here is **corroboration, not confirmation**. Two paths pointing at the same
span makes it more likely that span is the real payment field; it proves nothing on its
own, and it is not a licence to pay. Everything downstream still runs: the origin check,
the vendor master, the privileged-field rule. This layer can only ever *add* a reason to
escalate. It can never clear one -- `escalates` is the only thing it returns, and
`praetor/gate.py` keeps the last word.

That asymmetry is deliberate and is pinned by `tests/test_corroboration.py`. A
corroboration layer that could release a payment would be a new way to authorise one,
and every mechanism that can authorise a payment is a mechanism worth attacking.

## The honest limit

FINDINGS §17 measures where this stops. An attacker who stops writing sentences and
writes a bare account-shaped token, placed where a payment field sits, beats Path B --
75 times over 350 documents. Two paths do not make an attack impossible. They make the
*same* attack have to work twice, by two mechanisms with no common input, and they turn
the residue into an escalation rather than a payment.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Outcome", "corroborate", "AGREED", "DISAGREE", "NO_SECOND_OPINION",
           "NO_FIRST_OPINION"]

AGREED = ""
DISAGREE = "PATHS_DISAGREE"
NO_SECOND_OPINION = "NO_SECOND_OPINION"
NO_FIRST_OPINION = "NO_FIRST_OPINION"


@dataclass(frozen=True)
class Outcome:
    """What the two paths said, and whether that is enough to go on.

    `code` is a stable token, never a sentence: `dashboard/language.py` owns every word
    a person reads, and a wording change must not be able to break a caller.
    """
    agreed: bool
    code: str
    path_a: str | None
    path_b: str | None
    detail: str = ""

    @property
    def escalates(self) -> bool:
        """The only judgement this layer makes. There is no path to `pay` from here."""
        return not self.agreed


def corroborate(path_a: str | None, path_b) -> Outcome:
    """Compare the two paths' answers for one privileged field.

    `path_a` is a span id from the model. `path_b` is a `praetor.pathb.Pick`, or any
    object with `span_id`, or a span id, or None.

    Four outcomes, and three of them escalate:

      both named the same span      corroborated -- and still subject to every check
                                    downstream
      they named different spans    escalate. Deliberately NOT resolved by preferring
                                    one: preferring Path A restores the single point of
                                    failure this exists to remove, and preferring Path B
                                    hands the decision to the weaker extractor
      Path B abstained              escalate. A second opinion that guesses is worse than
                                    none, because agreement by coincidence is
                                    indistinguishable from corroboration
      Path A returned nothing       escalate. There is nothing to corroborate
    """
    b_span = getattr(path_b, "span_id", path_b)
    a = (path_a or "").strip() or None
    b = (str(b_span).strip() or None) if b_span is not None else None

    if a is None:
        return Outcome(False, NO_FIRST_OPINION, a, b,
                       "the reader did not identify the field")
    if b is None:
        reason = getattr(path_b, "reason", "") or "abstained"
        return Outcome(False, NO_SECOND_OPINION, a, b,
                       f"the second path had no opinion ({reason})")
    if a != b:
        return Outcome(False, DISAGREE, a, b,
                       "the two paths identified different parts of the document")
    return Outcome(True, AGREED, a, b, "both paths identified the same part")
