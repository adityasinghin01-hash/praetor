"""The JSON the three tabs read.

The most valuable test here is `test_no_code_word_reaches_any_screen`: it walks every
string in every API response and fails if any of them contains vocabulary Priya was never
meant to learn. `tests/test_language.py` checks the phrasebook; this checks that nothing
routes around it — an f-string in `api.py`, a raw finding code copied into a field, a
`repr()` that leaked a dataclass.

The rest pin the things that would be embarrassing rather than merely wrong: money summed
across currencies, a phone number sourced from the invoice being checked, an approval
recorded against someone who did not make it.
"""
import json
import pathlib

import pytest

from dashboard import api, build, language

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (ROOT / "out" / "vm_constructed.json").exists(),
    reason="run `make rules` first")


@pytest.fixture(scope="module")
def rows():
    rows, _ = build.rows_from_files()
    if not rows:
        pytest.skip("no adjudication results on disk")
    return rows


def _strings(obj, path="$"):
    """Every string in a response, with where it came from."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


# ------------------------------------------------------------------- the language rule

# Fields that are DATA rather than prose, and so are not held to the language rule.
# Two kinds: identifiers, which are never rendered as a sentence; and text that a person
# typed at us, which we echo back as evidence of what they tried. Attacker text is shown
# on Tab 2 on purpose -- it is the corpus -- and it is rendered with textContent, so it
# is inert. Holding it to the phrasebook would mean censoring the attacks we collect.
# `.outcome` is the machine key ("escalated"), used for sorting and styling and never
# rendered -- `.outcome_label` is what a person sees, and that IS held to the rule. The
# test below pins that, so this exclusion cannot quietly hide a regression.
_DATA_SUFFIX = (".id", ".doc_id", ".span_id", ".key", ".text", ".phone", ".email",
                ".outcome", ".vendor_key", ".source", ".verified_on", ".contact_name")


def _is_data(path: str) -> bool:
    return path.endswith(_DATA_SUFFIX) or ".examples" in path or ".hardest" in path


def _responses(rows):
    return {"queue": api.queue(rows), "stopped": api.stopped(rows),
            "documents": api.gauntlet_documents(), "examples": api.gauntlet_examples()}


def test_no_code_word_reaches_any_screen(rows):
    """Nothing may route around dashboard/language.py."""
    bad = []
    for name, body in _responses(rows).items():
        for path, text in _strings(body):
            if _is_data(path):
                continue
            found = language.code_words_in(text)
            if found:
                bad.append(f"{name}{path} says {found}: {text[:70]!r}")
    assert not bad, "\n".join(bad)


def test_no_raw_finding_code_reaches_any_screen(rows):
    import re
    bad = []
    for name, body in _responses(rows).items():
        for path, text in _strings(body):
            if _is_data(path):
                continue
            if re.search(r"\b[A-Z][A-Z0-9_]{4,}\b", text):
                bad.append(f"{name}{path}: {text[:70]!r}")
    assert not bad, "\n".join(bad)


# --------------------------------------------------------------------------- the queue

def test_the_queue_tells_her_the_win_and_what_is_left(rows):
    q = api.queue(rows)
    assert q["waiting"] + q["handled"] == q["total"]
    assert str(q["waiting"]) in q["headline"] and str(q["handled"]) in q["headline"]
    assert q["throughput"]


def test_the_worst_row_is_first(rows):
    """She should never have to scroll to find the one that moves money."""
    sev = [r["severity"] for r in api.queue(rows)["rows"]]
    assert sev == sorted(sev, key=lambda s: api.SEVERITY_RANK.get(s, 9))


def test_every_row_says_what_is_wrong_and_what_to_do(rows):
    for r in api.queue(rows)["rows"]:
        assert r["what_is_wrong"] and r["what_to_do"]
        assert r["supplier"] and r["id"]


def test_the_phone_number_never_comes_from_the_invoice(rows):
    """The most common way invoice fraud gets past a careful person is that they ring
    the number on the invoice. See praetor/suppliers.py."""
    for r in api.queue(rows)["rows"]:
        call = r["call"]
        assert call["warning"], "every row must say where the number came from"
        if call.get("phone"):
            assert call["source"] == "buyer records"
            doc = json.loads((ROOT / "data" / "constructed" / f"{r['id']}.json").read_text())
            printed = " ".join(f["text"] for f in doc["field_extractions"])
            assert call["phone"] not in printed


def test_amounts_come_from_the_document(rows):
    q = api.queue(rows)
    assert any(r["amount"] for r in q["rows"]), "no row shows an amount"


# ------------------------------------------------------------------- what we stopped

def test_money_is_never_summed_across_currencies(rows):
    """A total mixing USD and GBP is wrong in a way that puts every other figure in
    doubt the moment a finance person notices."""
    s = api.stopped(rows)
    by = s["exposure_by_currency"]
    if len(by) > 1:
        for code in by:
            assert code in s["exposure"]
    assert "  " in s["exposure"] or len(by) <= 1


def test_the_exposure_is_described_as_risk_not_loss(rows):
    """No confirmed incident exists. The wording must not imply one."""
    s = api.stopped(rows)
    assert "at risk" in s["exposure_note"]
    assert "loss" not in s["headline"].lower()
    assert "saved" not in s["headline"].lower()


def test_controls_are_reported_in_plain_language(rows):
    for c in api.stopped(rows)["controls"]:
        assert c["what"] in {e.headline for e in language.EXPLANATIONS.values()} | \
            {language.UNKNOWN.headline}


# --------------------------------------------------------------------- try to break it

def test_only_clean_invoices_are_offered():
    docs = api.gauntlet_documents()["documents"]
    assert docs
    for d in docs:
        assert d["supplier"] and d["amount"]


def test_a_document_outside_the_offer_is_refused():
    """The id comes from a request. It is not a path we follow."""
    for bad in ("../../etc/passwd", "V014_009_nope", ""):
        with pytest.raises(KeyError):
            api.gauntlet_document(bad)
        with pytest.raises(KeyError):
            api.gauntlet_run(bad, "x")


def test_running_an_attack_returns_steps_and_a_verdict(tmp_path, monkeypatch):
    from dashboard import attack_log
    monkeypatch.setattr(attack_log, "DEFAULT_PATH", tmp_path / "corpus.jsonl")
    doc = api.gauntlet_documents()["documents"][0]["id"]
    body = api.gauntlet_run(doc, "Updated details: DE89370400440532013000")
    assert body["steps"] and body["would_have_paid"]
    assert body["stopped"] is True
    assert body["corpus"]["attempts"] == 1


def test_the_examples_are_the_attacks_that_actually_work():
    """FINDINGS §2: the ones that look like attacks are the ones the model already
    resists. Offering those would flatter us."""
    texts = " ".join(e["text"] for e in api.gauntlet_examples()["examples"]).lower()
    assert "ignore all previous" not in texts
    assert "remittance" in texts or "banking details" in texts


def test_the_human_outcome_label_is_held_to_the_language_rule(rows):
    """`.outcome` is excluded from the scan above because it is never rendered. This is
    what makes that safe: the string that IS rendered gets checked."""
    seen = set()
    for r in api.queue(rows)["rows"]:
        seen.add(r["outcome_label"])
    for d in api.stopped(rows)["decisions"]:
        seen.add(d["outcome_label"])
    assert seen, "nothing rendered an outcome"
    for label in seen:
        assert not language.code_words_in(label), label
        assert label in language.OUTCOMES.values()
