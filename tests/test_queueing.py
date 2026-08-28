"""Queue ordering, and the two things it must never become.

Priya works ~300 documents a day, so whatever sits at the bottom is looked at last and,
on a bad day, not at all. That makes ordering security-relevant:

  * **it may never filter** -- a ranker that can drop an item can hide one, and "make
    the fraudulent invoice low priority" is strictly easier than "make the fraudulent
    invoice look legitimate";
  * **it may never be unexplainable** -- a queue whose order cannot be justified is a
    queue she learns to ignore.

The first is asserted as a permutation property over generated inputs rather than on one
example, because it is the one an attacker would go after.
"""
from __future__ import annotations

import itertools
import random

from praetor.queueing import PRIOR, UNKNOWN_CODE_WEIGHT, learn, order

CODES = ["IMPOSSIBLE_ORIGIN", "TAINTED_ACCOUNT_NOT_IN_MASTER", "FIRST_TIME_VENDOR",
         "MISSING_FIELD", "A_CODE_NOBODY_HAS_SEEN"]


def _queue(n: int, rng: random.Random) -> list[dict]:
    return [{"doc_id": f"D{i:03d}",
             "codes": rng.sample(CODES, rng.randint(0, 3)),
             "amount": f"{rng.uniform(1, 5_000_000):,.2f}"} for i in range(n)]


# ------------------------------------------------------------------ it may never filter

def test_ordering_is_always_a_permutation():
    """Generated queues, and the set of documents must survive every one."""
    rng = random.Random(7)
    for n in (0, 1, 2, 5, 40, 200):
        items = _queue(n, rng)
        result = order(items)
        assert sorted(result.keys) == sorted(i["doc_id"] for i in items)
        assert len(result.items) == n


def test_no_amount_or_code_combination_can_drop_an_item():
    """The direct form of the same claim, over every small combination."""
    for codes in itertools.chain.from_iterable(
            itertools.combinations(CODES, r) for r in range(len(CODES) + 1)):
        for amount in (None, "", "0", "-5", "not a number", "999,999,999.99"):
            items = [{"doc_id": "keep-me", "codes": list(codes), "amount": amount}]
            assert order(items).keys == ["keep-me"]


def test_there_is_no_way_to_ask_for_fewer_items():
    """A limit or threshold parameter would be the filtering this forbids, arriving as a
    convenience. If one is ever added, this test is where the argument has to happen."""
    import inspect

    params = set(inspect.signature(order).parameters)
    assert not (params & {"limit", "top", "cutoff", "threshold", "min_score", "head"})


def test_an_unknown_finding_sorts_mid_queue_and_never_last():
    """A finding nobody has weighted yet must not become invisible by default. That is
    how a new detector's first real catch gets buried."""
    items = [{"doc_id": "known-low", "codes": ["MISSING_FIELD"]},
             {"doc_id": "unknown", "codes": ["A_CODE_NOBODY_HAS_SEEN"]},
             {"doc_id": "known-high", "codes": ["IMPOSSIBLE_ORIGIN"]}]
    assert order(items).keys == ["known-high", "unknown", "known-low"]
    assert PRIOR["MISSING_FIELD"] < UNKNOWN_CODE_WEIGHT < PRIOR["IMPOSSIBLE_ORIGIN"]


# ------------------------------------------------------------------ it may never be opaque

def test_every_item_says_why_it_sits_where_it_does():
    ranked = order([{"doc_id": "d", "codes": ["IMPOSSIBLE_ORIGIN"]}]).items
    assert ranked[0].why and "IMPOSSIBLE_ORIGIN" in ranked[0].why[0]


def test_an_amount_can_never_outrank_a_finding():
    """A large clean invoice is not more urgent than a small one paying an account
    nobody recognises. The amount is a tie-break, bounded, and that is on purpose."""
    items = [{"doc_id": "huge-but-mild", "codes": ["MISSING_FIELD"],
              "amount": "999,999,999.99"},
             {"doc_id": "tiny-but-serious", "codes": ["IMPOSSIBLE_ORIGIN"],
              "amount": "1.00"}]
    assert order(items).keys[0] == "tiny-but-serious"


# ------------------------------------------------------------------ what it learned

def test_with_no_decisions_it_is_the_prior_and_says_so():
    """docs/PLAN.md: build the pipes, never claim the water. The decision record holds
    0 human decisions, so this must report that rather than imply a ranking."""
    result = order([{"doc_id": "d", "codes": ["FIRST_TIME_VENDOR"]}], decisions=[])
    assert result.learned_from == 0
    assert result.is_prior_only
    assert result.adjusted_codes == ()


def test_a_code_people_keep_approving_sinks():
    decisions = [{"codes": ["FIRST_TIME_VENDOR"], "approved": True} for _ in range(10)]
    adjustment = learn(decisions)
    assert adjustment["FIRST_TIME_VENDOR"] < 0

    items = [{"doc_id": "sinks", "codes": ["FIRST_TIME_VENDOR"]},
             {"doc_id": "stays", "codes": ["CURRENCY_MISMATCH"]}]
    assert order(items).keys == ["sinks", "stays"]           # prior order
    assert order(items, decisions).keys == ["stays", "sinks"]  # learned order


def test_a_code_people_keep_refusing_rises():
    decisions = [{"codes": ["CURRENCY_MISMATCH"], "approved": False} for _ in range(10)]
    assert learn(decisions)["CURRENCY_MISMATCH"] > 0


def test_one_decision_teaches_nothing():
    """Ranking on one or two decisions is copying the last thing that happened, and it
    would let a single mistaken approval push a whole class of finding down the queue."""
    assert learn([{"codes": ["FIRST_TIME_VENDOR"], "approved": True}]) == {}
    assert learn([{"codes": ["FIRST_TIME_VENDOR"], "approved": True}] * 4) == {}
    assert learn([{"codes": ["FIRST_TIME_VENDOR"], "approved": True}] * 5) != {}


def test_learning_still_cannot_drop_an_item():
    """The permutation property has to survive the learned path too, not just the prior."""
    decisions = [{"codes": ["IMPOSSIBLE_ORIGIN"], "approved": True} for _ in range(50)]
    items = _queue(30, random.Random(3))
    assert sorted(order(items, decisions).keys) == sorted(i["doc_id"] for i in items)
