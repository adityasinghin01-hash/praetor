"""Two paths must agree, and agreement must never be a way to authorise a payment."""
from __future__ import annotations

import ast
import itertools
import sys
from pathlib import Path

from praetor import corroboration
from praetor.corroboration import (AGREED, DISAGREE, NO_FIRST_OPINION,
                                   NO_SECOND_OPINION, corroborate)
from praetor.pathb import Pick

SOURCE = Path(corroboration.__file__)

A = "p0:0.0800_0.7800_0.5200_0.8100"
B = "p0:0.0800_0.6200_0.9200_0.6600"


def test_imports_only_the_standard_library():
    tree = ast.parse(SOURCE.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert not [r for r in roots if r not in sys.stdlib_module_names]


def test_same_span_is_corroborated():
    out = corroborate(A, A)
    assert out.agreed and out.code == AGREED and not out.escalates


def test_different_spans_escalate_and_neither_path_wins():
    """Deliberately not resolved by preferring one path.

    Preferring Path A restores the single point of failure this exists to remove;
    preferring Path B hands the decision to the weaker extractor. There is no winner,
    so a person looks.
    """
    out = corroborate(A, B)
    assert out.code == DISAGREE and out.escalates
    assert out.path_a == A and out.path_b == B     # both are reported, neither chosen


def test_an_abstention_escalates_and_says_why():
    out = corroborate(A, Pick(None, None, 0.31, 0.02, "margin_too_small"))
    assert out.code == NO_SECOND_OPINION and out.escalates
    assert "margin_too_small" in out.detail


def test_no_answer_from_the_reader_escalates():
    for empty in (None, "", "   "):
        assert corroborate(empty, A).code == NO_FIRST_OPINION


def test_it_accepts_a_pick_a_bare_span_id_or_nothing():
    """Callers should not have to convert between three shapes of the same answer."""
    assert corroborate(A, Pick(A, 0, 0.99, 0.9)).agreed
    assert corroborate(A, A).agreed
    assert corroborate(A, None).code == NO_SECOND_OPINION


def test_whitespace_is_not_a_disagreement():
    assert corroborate(f"  {A}  ", A).agreed


def test_this_layer_can_only_ever_escalate():
    """The property that makes it safe to add at all.

    A corroboration layer that could release a payment would be a new way to authorise
    one, and every mechanism that can authorise a payment is worth attacking. So the
    only judgement it exposes is `escalates`, and over every combination of inputs it
    is False exactly when the two paths named the same span -- which still leaves every
    check downstream to run.
    """
    values = [None, "", A, B, Pick(A, 0, 0.9, 0.8), Pick(B, 1, 0.9, 0.8),
              Pick(None, None, 0.2, 0.01, "below_threshold")]
    for a, b in itertools.product(values, values):
        out = corroborate(a if isinstance(a, (str, type(None))) else a.span_id, b)
        span_b = getattr(b, "span_id", b)
        agreed_on_a_real_span = bool(
            getattr(a, "span_id", a)) and getattr(a, "span_id", a) == span_b
        assert out.escalates is not agreed_on_a_real_span
        assert out.agreed is agreed_on_a_real_span
        # There is no code path that returns anything resembling an approval.
        assert not hasattr(out, "approve") and not hasattr(out, "pay")


def test_outcome_codes_are_tokens_not_sentences():
    """dashboard/language.py owns the words a person reads. A wording change here must
    not be able to break a caller or leak a code word onto a screen."""
    for code in (AGREED, DISAGREE, NO_SECOND_OPINION, NO_FIRST_OPINION):
        assert code == code.upper()
        assert " " not in code
