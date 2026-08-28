"""What a span looks like, never what it says.

This is the input layer for PRAETOR's second extraction path. Path A is a model: it
reads the document, understands it, and is therefore movable by any sentence an attacker
can write. This file exists so that the second path cannot be.

**The rule: no feature in this file reads a word.** There is no vocabulary, no keyword
list, no substring match against natural language, and no way to add one without the
tests noticing. A span becomes a vector of three kinds of thing:

    geometry          where the span sits on the page, absolutely and relative to
                      every other span on it
    character ratios  how much of the text is digits, capitals, spaces, punctuation;
                      how long the runs are
    checksums         whether the longest token is shaped like an account number, and
                      whether it passes the arithmetic that account numbers pass

"Please note our updated banking details" and "Thank you for your continued business"
produce the *same vector* if their characters fall into the same classes. That is the
whole point: FINDINGS §2 found that the twelve payloads which beat a model all read like
ordinary business correspondence. Reading is the vulnerability. So the second path does
not read.

## The honest limit, stated up front

An attacker still controls the text, so they still control the ratios. What they cannot
do is move this path *by writing a sentence*. To fool it they must produce a span that is
shaped like an account number and sits where an account number sits -- at which point
they are no longer writing prose, and `praetor/canary.py`, which reads the document's own
label and not the text at all, is the next thing in the way. The claim is decorrelation
from Path A, not invulnerability. See FINDINGS §17 for the payload that does beat it.

## Why every feature is already in [0, 1]

No scaler is fitted, exported or loaded. A standardiser is state that has to travel with
the weights and can silently drift out of step with them; bounding the features by
construction means the vector this file produces today is the vector it produced when the
weights were fitted, and a test can check that directly.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

__all__ = ["FEATURE_NAMES", "GEOMETRY_FEATURES", "CONTENT_FEATURES",
           "span_features", "document_features", "iban_mod97", "luhn"]

# The longest run of letters and digits in a span, which is the only "token" this file
# has an opinion about. Deliberately not a word: it cannot match prose.
_ALNUM_RUN = re.compile(r"[A-Za-z0-9]+")
_DIGIT_RUN = re.compile(r"\d+")

# An account-number *shape*: two letters, two digits, then ten to thirty more
# alphanumerics. This is a structural test, not a semantic one -- it would match a
# meaningless string of the same shape, which is exactly the property wanted.
_ACCOUNT_SHAPE = re.compile(r"^[A-Za-z]{2}\d{2}[A-Za-z0-9]{10,30}$")

# Where the span sits on the page, absolutely and relative to every other span.
#
# **These are computed and are NOT in the shipped fit.** Held out by layout, geometry
# reaches 0.208 on its own, costs 0.020 when added to the rest -- and, far worse, is the
# feature an adaptive attacker uses: it teaches the path "the payment field is low on
# the page", so a token placed low on the page inherits the belief. Removing it turned
# 67 documents where Path B took the attacker's span instead of the real account into
# abstentions. Position is the one thing an attacker fully controls, so a path that reads
# position is a path they can write to. Measured in FINDINGS §17; the exclusion is pinned
# by tests/test_pathb.py.
#
# They stay in the file because the finding has to remain reproducible, and because a
# feature deleted is a measurement nobody can repeat.
GEOMETRY_FEATURES: tuple[str, ...] = (
    "x_centre", "y_centre", "width", "height", "left", "bottom", "landscape",
    "y_rank", "x_rank", "width_rank", "area_rank",
)

# What the span is made of, and whether it is shaped like an account number. No word is
# read to compute any of these.
CONTENT_FEATURES: tuple[str, ...] = (
    "digit_ratio", "upper_ratio", "lower_ratio", "space_ratio", "punct_ratio",
    "length", "tokens", "max_digit_run", "max_alnum_run", "digit_runs",
    "account_shape", "mod97", "luhn",
)

FEATURE_NAMES: tuple[str, ...] = GEOMETRY_FEATURES + CONTENT_FEATURES


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def iban_mod97(text: str) -> bool:
    """The ISO 13616 check: move the first four characters to the end, map letters to
    numbers, and the whole thing modulo 97 must be 1.

    Arithmetic over characters, with no idea what any of them mean. A string that passes
    is a string whose check digits were computed; that is all it tells you, and it is a
    fact about the string rather than about the sentence around it.
    """
    s = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    if not (15 <= len(s) <= 34) or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    rotated = s[4:] + s[:4]
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rotated)
    return digits.isdigit() and int(digits) % 97 == 1


def luhn(digits: str) -> bool:
    """The check that runs on card and some account numbers. Same character arithmetic."""
    if not digits.isdigit() or len(digits) < 12:
        return False
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _text_features(text: str) -> dict[str, float]:
    t = text or ""
    n = len(t)
    if n == 0:
        return {k: 0.0 for k in CONTENT_FEATURES}

    digits = sum(c.isdigit() for c in t)
    upper = sum(c.isupper() for c in t)
    lower = sum(c.islower() for c in t)
    spaces = sum(c.isspace() for c in t)
    punct = n - digits - upper - lower - spaces

    alnum_runs = _ALNUM_RUN.findall(t)
    digit_runs = _DIGIT_RUN.findall(t)
    longest_alnum = max(alnum_runs, key=len) if alnum_runs else ""
    longest_digits = max(digit_runs, key=len) if digit_runs else ""

    return {
        "digit_ratio": digits / n,
        "upper_ratio": upper / n,
        "lower_ratio": lower / n,
        "space_ratio": spaces / n,
        "punct_ratio": punct / n,
        # Bounded rather than scaled. 120 characters is well past any field on an
        # invoice and well inside any injected paragraph, so the cap loses nothing
        # that separates the two.
        "length": _clip01(n / 120.0),
        "tokens": _clip01(len(alnum_runs) / 30.0),
        "max_digit_run": _clip01(len(longest_digits) / 20.0),
        "max_alnum_run": _clip01(len(longest_alnum) / 40.0),
        "digit_runs": _clip01(len(digit_runs) / 10.0),
        "account_shape": float(bool(_ACCOUNT_SHAPE.match(longest_alnum))),
        "mod97": float(iban_mod97(longest_alnum)),
        "luhn": float(luhn(longest_digits)),
    }


def span_features(text: str, bbox: Sequence[float], page: int = 0,
                  ranks: Mapping[str, float] | None = None) -> list[float]:
    """One span's vector, in `FEATURE_NAMES` order.

    `ranks` carries the four document-relative features, which cannot be computed from
    one span alone. Absent, they are 0.5 -- the value a span would take in a document
    where every span is identical, which is the least informative answer rather than an
    arbitrary one.
    """
    l, t, r, b = (list(bbox) + [0.0, 0.0, 0.0, 0.0])[:4]
    w, h = max(r - l, 0.0), max(b - t, 0.0)
    rk = dict(ranks or {})
    geom = {
        "x_centre": _clip01((l + r) / 2.0),
        "y_centre": _clip01((t + b) / 2.0),
        "width": _clip01(w),
        "height": _clip01(h),
        "left": _clip01(l),
        "bottom": _clip01(b),
        # Shape without an unbounded ratio: 1.0 is a wide flat span, 0.0 a tall narrow
        # one. Every real field on an invoice is a line of text, so this mostly
        # separates a single field from a paragraph.
        "landscape": _clip01(w / (w + h)) if (w + h) > 0 else 0.5,
        "y_rank": rk.get("y_rank", 0.5),
        "x_rank": rk.get("x_rank", 0.5),
        "width_rank": rk.get("width_rank", 0.5),
        "area_rank": rk.get("area_rank", 0.5),
    }
    geom.update(_text_features(text))
    return [float(geom[name]) for name in FEATURE_NAMES]


def _rank(values: list[float], i: int) -> float:
    """Fraction of the other spans this one is strictly greater than.

    Rank rather than raw value is what lets a path trained on four page templates say
    anything about a fifth. "Lower down than most of the page" survives a layout change;
    "at y = 0.78" does not.
    """
    if len(values) < 2:
        return 0.5
    return sum(1 for v in values if v < values[i]) / (len(values) - 1)


def document_features(spans: Sequence[Mapping]) -> list[list[float]]:
    """Every span in one document, vectorised together so the ranks are meaningful.

    Each element needs `text` and `bbox`; `page` is optional. This is deliberately the
    raw annotation shape rather than a new type -- the fewer conversions between the
    document and the thing that judges it, the fewer places a mismatch can hide.
    """
    if not spans:
        return []
    boxes = []
    for s in spans:
        l, t, r, b = (list(s.get("bbox") or []) + [0.0, 0.0, 0.0, 0.0])[:4]
        boxes.append((l, t, max(r - l, 0.0), max(b - t, 0.0)))
    ys = [t + h / 2.0 for _, t, _, h in boxes]
    xs = [l + w / 2.0 for l, _, w, _ in boxes]
    ws = [w for _, _, w, _ in boxes]
    areas = [w * h for _, _, w, h in boxes]

    out = []
    for i, s in enumerate(spans):
        out.append(span_features(
            str(s.get("text", "")), s.get("bbox") or [0, 0, 0, 0],
            int(s.get("page", 0) or 0),
            {"y_rank": _rank(ys, i), "x_rank": _rank(xs, i),
             "width_rank": _rank(ws, i), "area_rank": _rank(areas, i)},
        ))
    return out
