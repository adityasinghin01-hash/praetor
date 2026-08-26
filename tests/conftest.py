"""Test isolation.

Tests must never write production state. `adjudicate()` calls costguard.check() and
costguard.record() around every model call -- including the fake ones the tests inject --
so without this, running the suite inflates out/spend.json with calls that never
happened. It had climbed to Rs 9.92 of a Rs 10 ceiling, almost all of it fictional, and
the first thing that noticed was a real run being refused.

Two things go wrong when tests share a ledger with production: the spending figures we
publish become partly invented, and the ceiling that protects a live billing account can
be exhausted by CI.
"""
import pytest

from praetor import costguard


@pytest.fixture(autouse=True)
def isolated_spend_ledger(tmp_path, monkeypatch):
    """Point the ledger at a per-test temp file, for every test, without exception."""
    monkeypatch.setattr(costguard, "SPEND_FILE", tmp_path / "spend.json")
    yield
