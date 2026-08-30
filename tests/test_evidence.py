"""The comparison behind each finding.

The queue row has always said *what* was wrong. It did not say what the answer was, so
Priya went and looked it up — in a system that was already holding it. These tests pin
the half that closes that gap, and they are written against the real corpus rather than
fixtures because the value of this feature is entirely in whether it resolves against
actual supplier history.
"""
from __future__ import annotations

import pytest

from dashboard import api, build, language

pytestmark = pytest.mark.skipif(
    not (api.ROOT / "out" / "vm_constructed.json").exists(),
    reason="run `make rules` first")


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    raw, _ = build.rows_from_files()
    return api.queue(raw)["rows"]


def _all(rows) -> list[dict]:
    return [e for r in rows for e in r.get("evidence", [])]


def test_most_of_the_queue_carries_its_comparison(rows):
    """A feature that fires on a handful of rows would not change the job."""
    carrying = [r for r in rows if r.get("evidence")]
    assert len(carrying) > len(rows) * 0.8


def test_a_new_account_is_shown_beside_the_ones_already_paid(rows):
    """Priya's problem 1. Both accounts, side by side, from her own records."""
    bank = [e for e in _all(rows) if e["kind"] == "account"]
    assert bank
    for e in bank:
        assert e["on_invoice"], "the account on the invoice must be shown"
        assert e["in_records"], "the accounts already paid must be shown"
        assert e["on_invoice"] not in e["in_records"], (
            "if the account were already known this finding would not exist")


def test_a_duplicate_names_the_original_document(rows):
    """Priya's problem 2. 'Did I already pay this' is answerable only if the original
    can actually be pointed at."""
    dupes = [e for e in _all(rows) if e["kind"] == "duplicate"]
    assert dupes
    assert any(e["in_records"] for e in dupes), (
        "a duplicate that cannot name the invoice it duplicates is not an answer")


def test_the_machines_own_code_never_reaches_the_screen(rows):
    """A screen switches on how a thing is shown, not on what the rule was called.
    tests/test_api.py enforces this across every response; this is it at close range."""
    for e in _all(rows):
        assert "code" not in e
        assert e["kind"].islower()


def test_the_field_names_are_words_a_person_uses(rows):
    for e in _all(rows):
        assert e["field"] == e["field"].strip()
        assert "_" not in e["field"], f"{e['field']} is a machine name"


def test_no_note_leaks_the_machine_s_vocabulary(rows):
    """The same guarantee dashboard/language.py makes everywhere else."""
    for e in _all(rows):
        note = (e["note"] or "").lower()
        for word in language.FORBIDDEN:
            assert word not in note, f"{word!r} reached a person in: {e['note']}"


def test_a_note_never_claims_more_than_the_data_supports():
    """The vendor master holds a mode, not a universal, so the words say 'usual'."""
    for code in ("CURRENCY_MISMATCH", "TAX_RATE_MISMATCH", "AMOUNT_OUT_OF_RANGE"):
        note = language.evidence_note(code, 13) or ""
        assert "usual" in note.lower()
        assert "always" not in note.lower()
        assert "every" not in note.lower()


def test_a_supplier_with_no_history_says_so_rather_than_implying_none_matched():
    note = language.evidence_note("BANK_UNKNOWN", 0) or ""
    assert "no earlier invoices" in note


def test_a_missing_field_finding_always_says_which_field(rows):
    """The rule and the screen must agree on what 'missing' means.

    They did not: the rule fires at EXPECTED_PRESENCE (0.8) and the evidence builder
    hardcoded 0.9, so a field present on 85% of a supplier's invoices raised
    MISSING_FIELD and then showed an empty comparison — the screen saying something was
    missing and declining to say what.
    """
    from praetor.baseline_rules import EXPECTED_PRESENCE

    for r in rows:
        if "missing" in {e["kind"] for e in r.get("evidence", [])}:
            for e in r["evidence"]:
                if e["kind"] == "missing":
                    assert e["field"], "a missing-field comparison must name the field"
                    assert e["note"], "and say how often they normally fill it in"
    # and the threshold is the rule's, not a copy
    assert EXPECTED_PRESENCE == 0.8
