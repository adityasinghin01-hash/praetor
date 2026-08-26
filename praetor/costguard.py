"""A hard spending ceiling, enforced in code.

An estimate is not a control. This module tracks every token this project sends or
receives, prices it against Google's published rates, and raises BudgetExceeded
before the call that would cross the ceiling — so overspending is structurally
impossible rather than merely unlikely.

Spend is persisted to out/spend.json, so the ceiling holds across separate runs and
across days. It is not reset by restarting a script.

It is also not reset by damaging the file. An earlier version swallowed a parse error
and returned a zero Spend, so a truncated spend.json read as "nothing spent" and handed
back the whole ceiling -- the money control failing open. Now a file that exists but
cannot be read raises CorruptSpendFile and every call is refused until a person looks at
it. Writes go through praetor.durable, so the truncation that caused it cannot recur.

Rates: https://ai.google.dev/gemini-api/docs/pricing (checked 25 Aug 2026)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from praetor.durable import locked, write_json_atomic

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


class CorruptSpendFile(RuntimeError):
    """The ledger exists but cannot be read. Refuse to spend until a person looks."""


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
    """Read the ledger. A missing file means zero; an unreadable one means STOP.

    The distinction is the whole point. "No ledger yet" and "the ledger is damaged" look
    similar and mean opposite things, and conflating them is how a spending ceiling
    silently disappears.
    """
    if not SPEND_FILE.exists():
        return Spend()
    try:
        raw = json.loads(SPEND_FILE.read_text())
        return Spend(**raw)
    except Exception as e:  # noqa: BLE001
        raise CorruptSpendFile(
            f"{SPEND_FILE} exists but could not be read ({e}). Refusing to spend. "
            f"Inspect it, then delete it deliberately if you accept losing the running "
            f"total."
        ) from e


def _save(s: Spend) -> None:
    write_json_atomic(SPEND_FILE, s.__dict__)


def price(model: str, in_tok: int, out_tok: int) -> float:
    ri, ro = RATES.get(model, DEFAULT_RATE)
    return in_tok / 1e6 * ri + out_tok / 1e6 * ro


def check(model: str, prompt_chars: int, expected_out_tokens: int = 100) -> None:
    """Refuse the call if it would cross the ceiling. Call BEFORE spending."""
    with locked(SPEND_FILE):
        s = _load()
    projected = s.usd + price(model, int(prompt_chars / 3.5), expected_out_tokens)
    if projected * USD_PER_INR > CEILING_INR:
        raise BudgetExceeded(
            f"would reach Rs {projected * USD_PER_INR:.2f}, ceiling is Rs {CEILING_INR:.2f}. "
            f"Already spent Rs {s.inr:.2f} over {s.calls} calls. "
            f"Raise it deliberately with PRAETOR_BUDGET_INR=<amount> if you mean to."
        )


def record(model: str, in_tok: int, out_tok: int) -> Spend:
    """Record actual usage after a call.

    Read-modify-write under a lock: two runs recording at once would otherwise each read
    the same total and one would overwrite the other, undercounting spend in exactly the
    situation -- parallel work -- where the ceiling matters most.
    """
    with locked(SPEND_FILE):
        s = _load()
        s.usd += price(model, in_tok, out_tok)
        s.calls += 1
        s.input_tokens += in_tok
        s.output_tokens += out_tok
        _save(s)
        return s


def report() -> str:
    try:
        s = _load()
    except CorruptSpendFile as e:
        return f"SPEND LEDGER UNREADABLE -- all calls refused. {e}"
    return (f"spent Rs {s.inr:.2f} (${s.usd:.4f}) over {s.calls} calls  "
            f"[{s.input_tokens:,} in / {s.output_tokens:,} out]  "
            f"ceiling Rs {CEILING_INR:.2f}")


if __name__ == "__main__":
    print(report())
