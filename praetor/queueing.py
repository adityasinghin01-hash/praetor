"""What Priya should look at first — and the two things ordering must never become.

An exception queue is a list of invoices somebody has to work through, and the order is
not cosmetic: she processes around 300 documents a day, so whatever sits at the bottom is
effectively looked at last and, on a bad day, not at all.

That makes ordering a security-relevant operation, and it makes two failure modes worth
naming before any ranking is written.

**Ordering may never filter.** A ranker that can drop an item is a ranker that can hide
one, and "make the fraudulent invoice low priority" is a strictly easier attack than
"make the fraudulent invoice look legitimate". `order()` returns a permutation, and
`tests/test_queueing.py` asserts the multiset in equals the multiset out on generated
inputs. There is no threshold, no cutoff, no `limit`.

**Ordering may never be unexplainable.** Every item carries the reason it sits where it
does. A queue whose order cannot be justified to the person working it is a queue she
learns to distrust and then ignores, at which point the ordering is worse than none.

## What it learns from, and why the honest answer is "nothing yet"

The intended signal is the record of decisions people actually made: if invoices carrying
a particular finding are almost always approved once a person looks, that finding should
sink; if they are usually refused, it should rise. `learn()` computes exactly that.

**The record currently holds 0 human decisions.** `docs/PLAN.md` says this about the
project's two empty data assets: build the pipes, never claim the water. So `learn()`
returns an empty table, `order()` falls back to the stated prior below, and
`Ordering.learned_from` reports the number it was built on — which is the number to
publish, rather than a ranking quality nobody can evidence.

The prior is a hand-written table, not a model. It is in this file rather than in a
config so that changing what Priya sees first is a code review.

No LLM in this file. Standard library only.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

__all__ = ["PRIOR", "Ordering", "Ranked", "learn", "order"]

# How much attention a finding deserves before anything has been learned. Higher sorts
# earlier. Hand-written, deliberately: these are policy, and policy should be readable.
#
# The shape of it: anything that moves money to a new place outranks anything that merely
# looks unusual, because the cost of being wrong is not symmetric.
PRIOR: dict[str, float] = {
    # money moving somewhere new, or somewhere structurally impossible
    "IMPOSSIBLE_ORIGIN": 100.0,
    "ACCOUNT_REFUSED_ELSEWHERE": 95.0,
    "TAINTED_ACCOUNT_NOT_IN_MASTER": 90.0,
    "BANK_UNKNOWN": 90.0,
    "ORIGIN_UNKNOWN": 80.0,
    # a claim the document makes about itself
    "UNVERIFIED_AUTHORITY": 70.0,
    "DUPLICATE_INVOICE": 60.0,
    # unusual, but not a payment instruction
    "AMOUNT_OUTSIDE_TOLERANCE": 50.0,
    "AMOUNT_OUT_OF_RANGE": 45.0,
    "UNKNOWN_VENDOR": 40.0,
    "FIRST_TIME_VENDOR": 35.0,
    "CURRENCY_MISMATCH": 30.0,
    "TAX_RATE_MISMATCH": 25.0,
    "ADDRESS_MISMATCH": 25.0,
    "MISSING_FIELD": 20.0,
}
UNKNOWN_CODE_WEIGHT = 55.0   # an unrecognised finding sorts mid-queue, never last


@dataclass(frozen=True)
class Ranked:
    """One queue item, its score, and why it scored that."""
    key: str
    score: float
    why: tuple[str, ...]


@dataclass
class Ordering:
    """A queue order, plus an honest account of what it was built from."""
    items: list[Ranked] = field(default_factory=list)
    learned_from: int = 0          # human decisions the adjustment used. Currently 0.
    adjusted_codes: tuple[str, ...] = ()

    @property
    def keys(self) -> list[str]:
        return [i.key for i in self.items]

    @property
    def is_prior_only(self) -> bool:
        """True when nothing has been learned. Printed rather than hidden."""
        return self.learned_from == 0


def learn(decisions: Iterable[Mapping], min_observations: int = 5) -> dict[str, float]:
    """Per-finding adjustment from decisions people actually made.

    `decisions` are rows with `codes` and an `approved` flag: True when a person approved
    the payment, False when they refused it. A code whose invoices are usually approved
    is costing attention and sinks; one usually refused rises.

    A code seen fewer than `min_observations` times is left alone. Ranking on one or two
    decisions is not learning, it is copying the last thing that happened, and it would
    let a single mistaken approval push a whole class of finding down the queue.
    """
    seen: dict[str, int] = {}
    refused: dict[str, int] = {}
    for row in decisions:
        approved = bool(row.get("approved"))
        for code in row.get("codes") or ():
            seen[code] = seen.get(code, 0) + 1
            refused[code] = refused.get(code, 0) + (0 if approved else 1)

    out: dict[str, float] = {}
    for code, n in seen.items():
        if n < min_observations:
            continue
        rate = refused[code] / n
        # Centred on 0.5, so a code refused half the time is left where the prior put it.
        out[code] = (rate - 0.5) * 40.0
    return out


def order(items: Sequence[Mapping], decisions: Iterable[Mapping] = (),
          min_observations: int = 5) -> Ordering:
    """Sort a queue. Returns a permutation of `items`, never a subset.

    Each item needs `doc_id` and `codes`; `amount` is optional and used only to break
    ties, because two invoices with identical findings are not equally expensive to get
    wrong.
    """
    rows = list(decisions)
    adjustment = learn(rows, min_observations)

    ranked: list[Ranked] = []
    for item in items:
        codes = list(item.get("codes") or ())
        if codes:
            base = max(PRIOR.get(c, UNKNOWN_CODE_WEIGHT) for c in codes)
            driver = max(codes, key=lambda c: PRIOR.get(c, UNKNOWN_CODE_WEIGHT))
        else:
            base, driver = 0.0, ""
        delta = sum(adjustment.get(c, 0.0) for c in codes)

        why: list[str] = []
        if driver:
            why.append(driver)
        if delta:
            why.append(f"adjusted {delta:+.1f} from {len(rows)} past decisions")
        elif rows:
            why.append("no code seen often enough to adjust")

        amount = _amount(item.get("amount"))
        ranked.append(Ranked(
            key=str(item.get("doc_id") or ""),
            # Amount contributes a small, bounded tie-break. It must not be able to
            # outrank a finding: a large clean invoice is not more urgent than a small
            # one paying an account nobody recognises.
            score=base + delta + min(amount / 1_000_000.0, 1.0),
            why=tuple(why)))

    ranked.sort(key=lambda r: (-r.score, r.key))
    return Ordering(items=ranked, learned_from=len(rows),
                    adjusted_codes=tuple(sorted(adjustment)))


def _amount(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return abs(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0.0
