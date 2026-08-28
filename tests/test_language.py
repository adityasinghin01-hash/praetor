"""The no-code-words rule, enforced instead of remembered.

The plain-language rule is easy to agree with and easy to lose. Someone adds a finding,
the queue renders `IMPOSSIBLE_ORIGIN` in a table cell because nothing stopped it, and a
month later the screen is full of vocabulary Priya was never meant to learn.

So the rule is a test, and it works in two directions:

**Nothing untranslated can reach the screen.** The codes are discovered from the source
of the modules that emit them, not from a list maintained by hand. Add a new finding to
`baseline_rules.py`, `gate.py` or `canary.py` and this fails until it has a sentence.

**Nothing translated may contain jargon.** Every string that can be displayed is scanned
for the words engineers use and Priya does not.
"""
import ast
import pathlib
import re

import pytest

from dashboard import language
from dashboard.language import EXPLANATIONS, FORBIDDEN, explain, outcome_sentence

ROOT = pathlib.Path(__file__).resolve().parents[1]
EMITTERS = ["praetor/baseline_rules.py", "praetor/gate.py", "praetor/canary.py"]
CODE = re.compile(r"^[A-Z][A-Z0-9_]{4,}$")


def _codes_in_source() -> set[str]:
    """Every SCREAMING_CASE string literal in the modules that raise findings.

    Discovered rather than listed, so a new finding cannot be added without either
    translating it or failing this test.
    """
    found: set[str] = set()
    for rel in EMITTERS:
        tree = ast.parse((ROOT / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if CODE.match(node.value):
                    found.add(node.value)
    return found


def _displayed_strings() -> list[tuple[str, str]]:
    """(where it came from, the string) for everything that can appear on screen."""
    out = []
    for code, e in EXPLANATIONS.items():
        out.append((f"{code}.headline", e.headline))
        out.append((f"{code}.what_to_do", e.what_to_do))
    out.append(("UNKNOWN.headline", language.UNKNOWN.headline))
    out.append(("UNKNOWN.what_to_do", language.UNKNOWN.what_to_do))
    for key, name in language.STEP_NAMES.items():
        out.append((f"STEP_NAMES[{key}]", name))
    for decision in ("resolve", "escalate"):
        for overridden in (True, False):
            for why in (None, "privileged field", "unverified authority: cites AP-88213",
                        "no pre-authorised rule holds for this exception", "something else"):
                out.append((f"outcome({decision},{overridden},{why})",
                            outcome_sentence(decision, overridden, why)))
    return out


def test_every_finding_the_system_can_emit_has_a_sentence():
    missing = sorted(c for c in _codes_in_source() if c not in EXPLANATIONS)
    assert missing == [], (
        f"these findings would reach Priya untranslated: {missing}. "
        f"Add them to dashboard/language.py.")


def test_the_discovery_actually_found_the_known_codes():
    """Teeth: if the scanner silently found nothing, the test above passes vacuously."""
    found = _codes_in_source()
    for expected in ("BANK_UNKNOWN", "DUPLICATE_INVOICE", "IMPOSSIBLE_ORIGIN",
                     "TAINTED_ACCOUNT_NOT_IN_MASTER"):
        assert expected in found
    assert len(found) >= 10


@pytest.mark.parametrize("where,text", _displayed_strings())
def test_no_screen_text_contains_a_code_word(where, text):
    found = language.code_words_in(text)
    assert not found, f"{where} says {found}: {text!r}"


@pytest.mark.parametrize("where,text", _displayed_strings())
def test_no_screen_text_contains_a_raw_finding_code(where, text):
    assert not re.search(r"\b[A-Z][A-Z0-9_]{4,}\b", text), \
        f"{where} shows a raw code: {text!r}"


@pytest.mark.parametrize("code", sorted(EXPLANATIONS))
def test_every_explanation_says_what_is_wrong_and_what_to_do(code):
    e = EXPLANATIONS[code]
    assert e.headline.strip() and e.headline.strip()[-1] in ".!?"
    assert e.what_to_do.strip(), f"{code} does not tell her what to do"
    assert e.severity in ("stop", "check")


def test_an_unrecognised_code_still_produces_a_usable_sentence():
    """It should never happen -- the first test sees to that -- but a blank cell in
    front of someone deciding on a payment is worse than a general sentence."""
    e = explain("SOMETHING_NOBODY_TRANSLATED")
    assert e.headline and e.what_to_do


def test_the_override_sentence_never_blames_the_analyst():
    """She did not do anything wrong; the system disagreed with the AI. Say that."""
    said = outcome_sentence("resolve", True, "privileged field")
    assert "we disagreed" in said.lower()
    assert "you" not in said.lower().split("because")[0]
