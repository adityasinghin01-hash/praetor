"""A hard spending ceiling, enforced in code.

An estimate is not a control. This module tracks every token this project sends or
receives, prices it against Google's published rates, and raises BudgetExceeded
before the call that would cross the ceiling — so overspending is structurally
impossible rather than merely unlikely.

Spend is persisted to out/spend.json, so the ceiling holds across separate runs and
across days. It is not reset by restarting a script.

Rates: https://ai.google.dev/gemini-api/docs/pricing (checked 25 Aug 2026)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

USD_PER_INR = 88.0  # for reporting only

# USD per 1M tokens (input, output)
RATES = {
    "gemini-3.5-flash":      (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}
DEFAULT_RATE = (1.50, 9.00)   # unknown model: assume the expensive one

SPEND_FILE = Path(__file__).resolve().parents[1] / "out" / "spend.json"

# Ceiling in rupees. Deliberately low: Aditya wants to see one small real charge
# land before anything larger runs. Raising it is a conscious act, not a default.
#   PRAETOR_BUDGET_INR=25 python3 eval/...
CEILING_INR = float(os.environ.get("PRAETOR_BUDGET_INR", "10"))


class BudgetExceeded(RuntimeError):
    """Raised before a call that would push spend past the ceiling."""


@dataclass
class Spend:
    usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def inr(self) -> float:
        return self.usd * USD_PER_INR


def _load() -> Spend:
    if SPEND_FILE.exists():
        try:
            return Spend(**json.loads(SPEND_FILE.read_text()))
        except Exception:  # noqa: BLE001
            pass
    return Spend()


def _save(s: Spend) -> None:
    SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPEND_FILE.write_text(json.dumps(s.__dict__, indent=1))


def price(model: str, in_tok: int, out_tok: int) -> float:
    ri, ro = RATES.get(model, DEFAULT_RATE)
    return in_tok / 1e6 * ri + out_tok / 1e6 * ro


def check(model: str, prompt_chars: int, expected_out_tokens: int = 100) -> None:
    """Refuse the call if it would cross the ceiling. Call BEFORE spending."""
    s = _load()
    projected = s.usd + price(model, int(prompt_chars / 3.5), expected_out_tokens)
    if projected * USD_PER_INR > CEILING_INR:
        raise BudgetExceeded(
            f"would reach Rs {projected * USD_PER_INR:.2f}, ceiling is Rs {CEILING_INR:.2f}. "
            f"Already spent Rs {s.inr:.2f} over {s.calls} calls. "
            f"Raise it deliberately with PRAETOR_BUDGET_INR=<amount> if you mean to."
        )


def record(model: str, in_tok: int, out_tok: int) -> Spend:
    """Record actual usage after a call."""
    s = _load()
    s.usd += price(model, in_tok, out_tok)
    s.calls += 1
    s.input_tokens += in_tok
    s.output_tokens += out_tok
    _save(s)
    return s


def report() -> str:
    s = _load()
    return (f"spent Rs {s.inr:.2f} (${s.usd:.4f}) over {s.calls} calls  "
            f"[{s.input_tokens:,} in / {s.output_tokens:,} out]  "
            f"ceiling Rs {CEILING_INR:.2f}")


if __name__ == "__main__":
    print(report())
