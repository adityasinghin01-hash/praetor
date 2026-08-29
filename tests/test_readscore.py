"""The shared scorer must reproduce the numbers already published from it.

`eval/readscore.py` was factored out of `eval/run_readpath.py` so the fine-tuned reader,
the base model, the Ollama reader and the hosted reader are scored by one function
instead of two that could drift. A refactor of a function that produces published figures
is only safe if the figures come back, so this replays the stored per-document rows and
asserts FINDINGS §10's numbers.

No model is called. The rows are the ones the original runs wrote.
"""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from eval.readscore import FIELDS, outcome, score_rows  # noqa: E402


def rows(name):
    p = ROOT / "results" / name
    if not p.exists():
        pytest.skip(f"{name} not present")
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_the_weak_reader_scores_what_findings_10_says():
    """Gemma 3 1b, one-layout corpus: precision 0.640, recall 0.274, F1 0.384.

    That is the 'was' column of §10's table -- the inflated number, kept because the
    reason it was inflated is the finding. If this changes, the scorer changed.
    """
    s = score_rows(rows("readpath.jsonl"))
    assert round(s.precision, 3) == 0.640
    assert round(s.recall, 3) == 0.274
    assert round(s.f1, 3) == 0.384
    assert (s.correct, s.wrong, s.missed, s.spurious) == (48, 27, 100, 0)


def test_the_capable_reader_scores_1_000():
    s = score_rows(rows("readpath_gemini.jsonl"))
    assert s.precision == 1.0 and s.recall == 1.0 and s.f1 == 1.0
    assert s.correct == 70


def test_absent_is_not_scored():
    """A field that is correctly nothing must not count as a success.

    Seven of the corpus's documents have no account at all. If `absent` counted as a
    true positive, a reader that returned nothing on those would be rewarded for it and
    the privileged field's score would be flattered by the documents that do not have one.
    """
    s = score_rows([{"fields": {f: "absent" for f in FIELDS}}])
    assert s.correct == 0 and s.precision == 0.0 and s.recall == 0.0 and s.f1 == 0.0


def test_outcomes_are_assigned_the_way_the_published_runs_assigned_them():
    assert outcome(None, None) == "absent"
    assert outcome("x", None) == "missed"
    assert outcome(None, "x") == "spurious"
    assert outcome("x", "x") == "correct"
    assert outcome("x", "y") == "wrong"
    assert outcome("x", " x ") == "correct"   # whitespace, not a difference


def test_a_reader_that_answers_nothing_scores_zero_not_one():
    """Teeth. Recall must punish silence: precision alone would be undefined-then-zero
    and an all-missed run must never come out looking clean."""
    s = score_rows([{"fields": {f: "missed" for f in FIELDS}} for _ in range(10)])
    assert s.f1 == 0.0 and s.missed == 70


def test_both_harnesses_use_this_scorer_and_neither_recomputes_it():
    """One definition of the metric, or the numbers in one FINDINGS table are not
    comparable. DECISIONS #15 is about exactly this: two copies of one idea drifting.

    Comments are stripped before scanning, because a guard in this repo has already
    passed by matching its own explanatory comment.
    """
    for rel in ("eval/run_readpath.py", "finetune/eval_reader.py"):
        src = (ROOT / rel).read_text()
        code = "\n".join(line.split("#")[0] for line in src.splitlines())
        assert "from eval.readscore import" in code, rel
        assert "score_rows(" in code, rel
        # the arithmetic must live in one place only
        assert "2 * precision * recall" not in code, f"{rel} recomputes F1"
        assert "tp / retrieved" not in code, f"{rel} recomputes precision"
