"""The second extraction path: it picks a span, and it cannot be talked into one.

Path A reads the document. That is its value and its vulnerability -- FINDINGS §2 found
that every injection which beat a model read like ordinary business correspondence, which
is to say the attack surface *is* comprehension. Path B is the same job done by a
mechanism with no comprehension in it: `praetor/features.py` turns each span into
character ratios and checksums, and this file scores those and picks one.

**It does not read position, and that was a measurement rather than a preference.** The
plan for this path specified geometry. Held out by layout, geometry scored 0.208 alone
and cost 0.020 when added to the rest -- and under an adaptive attack it was actively
harmful: it teaches the path that the payment field sits low on the page, so a token
placed low on the page inherits the belief. Dropping it turned 67 documents where Path B
took the attacker's span instead of the real account into abstentions. Position is the one
property of a document an attacker fully controls. FINDINGS §17.

    pick = extract(spans, layout="banded")
    pick.span_id     # the span it believes holds the account, or None
    pick.abstained   # True when it is not confident enough to have an opinion

## What the two paths give you together

They fail differently, which is the only property that makes two of anything worth
having. A sentence that moves Path A -- an authority claim, a fake policy, a plausible
remittance notice -- is invisible to Path B, because Path B has no way to read it. A span
crafted to move Path B must be shaped and placed like an account number, which stops it
being persuasive prose. `praetor/corroboration.py` requires both to agree and sends the
document to a person when they do not.

## Abstention is a first-class answer

A second opinion that guesses is worse than no second opinion, because agreement by
coincidence reads exactly like corroboration. So this path answers only when the best
span is both probable enough and clearly ahead of the runner-up; otherwise it abstains,
and abstention escalates. The two thresholds are fixed in the weights file, chosen once,
and never tuned against a test fold.

## Standard library only, and no fitting

The weights are read from `pathb_weights.json`, fitted offline by `eval/train_pathb.py`.
Inference is a dot product and a comparison. Nothing here imports anything outside the
standard library, and nothing here can be fitted at runtime -- a security path that
learns from the traffic it is judging is a security path an attacker can teach.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from praetor.features import FEATURE_NAMES, document_features

__all__ = ["Pick", "decide", "extract", "load_weights", "weights_for", "select"]

WEIGHTS_FILE = Path(__file__).with_name("pathb_weights.json")

_CACHE: dict[str, object] = {}


class WeightsUnavailable(RuntimeError):
    """No fitted weights on disk. Path B has no opinion and must not invent one."""


def load_weights(path: Path | str | None = None) -> dict:
    p = Path(path) if path else WEIGHTS_FILE
    key = str(p)
    if key not in _CACHE:
        if not p.exists():
            raise WeightsUnavailable(
                f"{p} not found. Run: python eval/train_pathb.py")
        _CACHE[key] = json.loads(p.read_text())
    return _CACHE[key]  # type: ignore[return-value]


def select(vectors: Sequence[Sequence[float]], names: Sequence[str],
           ) -> list[list[float]]:
    """Keep only the features the weights file names, in the order it names them.

    The shipped fit does not use the geometry features, and that is recorded as data
    rather than as a slice: a fit and a feature list that can drift apart silently is
    the same class of bug as a stale artifact rendering perfectly (DECISIONS #16). A
    name the current code cannot produce raises here rather than scoring something else.
    """
    try:
        idx = [FEATURE_NAMES.index(n) for n in names]
    except ValueError as e:
        raise ValueError(
            f"pathb_weights.json names a feature this build cannot compute: {e}") from e
    return [[row[i] for i in idx] for row in vectors]


def weights_for(layout: str | None, weights: Mapping | None = None) -> list[float]:
    """The coefficients to score a document of this layout with.

    A document whose layout was held out of a fit is scored by that fit -- which is the
    only way a reported number means generalisation rather than recall. An unknown layout
    falls back to the fit over everything, because there is nothing to hold out.
    """
    w = weights if weights is not None else load_weights()
    folds = w.get("folds") or {}
    if layout and layout in folds:
        return list(folds[layout])
    return list(w["full"])


@dataclass(frozen=True)
class Pick:
    """Which span, how sure, and -- when it declines -- why.

    `reason` is a structured token rather than a sentence, for the same reason
    `guard.OriginViolation` uses one: callers map it onto their own vocabulary, and
    `dashboard/language.py` owns the words a person reads.
    """
    span_id: str | None
    index: int | None
    probability: float
    margin: float
    reason: str = ""            # "" | "no_spans" | "below_threshold" | "margin_too_small"

    @property
    def abstained(self) -> bool:
        return self.span_id is None and self.index is None


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def decide(vectors: Sequence[Sequence[float]], beta: Sequence[float],
           min_p: float, min_margin: float) -> Pick:
    """Score every span, take the best, and abstain unless it is clearly the best.

    Kept separate from `extract` and free of any document type so the training harness
    scores documents through exactly this code rather than through a copy of it. Two
    implementations of a decision are two decisions.
    """
    if not vectors:
        return Pick(None, None, 0.0, 0.0, "no_spans")
    # zip() truncates to the shorter sequence, so a feature vector and a coefficient
    # vector of different widths would score silently and wrongly -- which is exactly
    # what happened when the shipped fit dropped to 13 features and a caller kept
    # passing 24. It abstained on all 350 documents and looked like a result.
    if len(beta) != len(vectors[0]) + 1:
        raise ValueError(
            f"{len(vectors[0])} features scored against {len(beta) - 1} coefficients. "
            f"Select the features the weights name -- see praetor.pathb.select().")
    probs = [_sigmoid(beta[0] + sum(b * v for b, v in zip(beta[1:], row)))
             for row in vectors]
    order = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    best = order[0]
    runner_up = probs[order[1]] if len(order) > 1 else 0.0
    margin = probs[best] - runner_up

    if probs[best] < min_p:
        return Pick(None, None, probs[best], margin, "below_threshold")
    if margin < min_margin:
        return Pick(None, None, probs[best], margin, "margin_too_small")
    return Pick(None, best, probs[best], margin)


def extract(spans: Sequence[Mapping], layout: str | None = None,
            weights: Mapping | None = None) -> Pick:
    """Which span holds the payable account, by shape and position alone.

    `spans` is the raw annotation shape -- each needs `text` and `bbox`. A span's
    *label* is deliberately not read: that is `praetor/canary.py`'s only input, and the
    two checks are worth having precisely because they share none.
    """
    w = weights if weights is not None else load_weights()
    beta = weights_for(layout, w)
    vectors = select(document_features(spans), w.get("feature_names", FEATURE_NAMES))
    pick = decide(vectors, beta,
                  float(w.get("min_p", 0.5)), float(w.get("min_margin", 0.2)))
    if pick.index is None:
        return pick
    span = spans[pick.index]
    l, t, r, b = (list(span.get("bbox") or []) + [0.0, 0.0, 0.0, 0.0])[:4]
    span_id = "p%d:%s" % (int(span.get("page", 0) or 0),
                          "_".join(f"{c:.4f}" for c in (l, t, r, b)))
    return Pick(span_id, pick.index, pick.probability, pick.margin)
