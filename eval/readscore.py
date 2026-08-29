"""One definition of extraction accuracy, shared by every reader we measure.

`eval/run_readpath.py` scores the hosted and the Ollama readers; `finetune/eval_reader.py`
scores the MLX base model and the fine-tune. Those numbers are compared against each other
in FINDINGS, so they cannot be computed by two functions that might drift. They are
computed here.

The per-document rows are the same shape either script writes, so an aggregate can be
recomputed from a stored `.jsonl` without calling a model again -- which is also how this
module is tested: `tests/test_readscore.py` replays `results/readpath.jsonl` and asserts
the published F1 comes back out.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

FIELDS = ("vendor_name", "invoice_number", "amount_total",
          "currency", "bank_account", "tax_rate", "vendor_address")

OUTCOMES = ("correct", "wrong", "missed", "spurious", "absent")


def outcome(expected: str | None, got: str | None) -> str:
    """What one field did. `absent` means correctly nothing: it is not scored."""
    if expected is None and got is None:
        return "absent"
    if got is None:
        return "missed"
    if expected is None:
        return "spurious"
    return "correct" if got.strip() == expected.strip() else "wrong"


@dataclass
class Score:
    per_field: dict[str, Counter] = field(default_factory=dict)

    @property
    def correct(self) -> int:
        return sum(c["correct"] for c in self.per_field.values())

    @property
    def wrong(self) -> int:
        return sum(c["wrong"] for c in self.per_field.values())

    @property
    def missed(self) -> int:
        return sum(c["missed"] for c in self.per_field.values())

    @property
    def spurious(self) -> int:
        return sum(c["spurious"] for c in self.per_field.values())

    @property
    def precision(self) -> float:
        retrieved = self.correct + self.wrong + self.spurious
        return self.correct / retrieved if retrieved else 0.0

    @property
    def recall(self) -> float:
        relevant = self.correct + self.wrong + self.missed
        return self.correct / relevant if relevant else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def score_rows(rows) -> Score:
    """Aggregate per-document rows of the form {"fields": {field: outcome}}."""
    per_field = {f: Counter() for f in FIELDS}
    for row in rows:
        for f, o in row.get("fields", {}).items():
            if f in per_field:
                per_field[f][o] += 1
    return Score(per_field=per_field)


def render(s: Score, title: str, documents: int) -> str:
    """The block both scripts print. One layout, so two runs can be read side by side."""
    out = ["=" * 66,
           f"EXTRACTION ACCURACY  ({documents} documents, {title})",
           f"  correct            {s.correct}",
           f"  wrong field        {s.wrong}",
           f"  missed             {s.missed}",
           f"  spurious           {s.spurious}",
           "",
           f"  precision {s.precision:.3f}   recall {s.recall:.3f}   F1 {s.f1:.3f}",
           "",
           "  by field:",
           f"    {'field':<18}{'correct':>8}{'wrong':>7}{'missed':>8}{'absent':>8}"]
    for f in FIELDS:
        c = s.per_field[f]
        out.append(f"    {f:<18}{c['correct']:>8}{c['wrong']:>7}"
                   f"{c['missed']:>8}{c['absent']:>8}")
    return "\n".join(out)
