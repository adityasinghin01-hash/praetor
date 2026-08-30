"""The language rule, extended to the React app.

`dashboard/language.py` owns every sentence a person reads, and `tests/test_language.py`
plus `tests/test_api.py` hold the server to it. A frontend is a new place for English to
appear, so it is a new place the rule can be broken -- by a hard-coded finding code, a
paraphrase of a translated sentence, or a word Priya was never meant to learn.

The runtime check lives in `web/src/screens/screens.test.tsx`, which walks the rendered DOM and
fails on any forbidden word. That is the right place for it: it tests what is actually on
screen rather than what is in the source.

What is tested HERE is that the two lists cannot drift apart. A vocabulary added to
`language.FORBIDDEN` that the frontend check has never heard of is a guard that passes
vacuously, which this project has now been bitten by twice.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from dashboard.language import FORBIDDEN

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"

pytestmark = pytest.mark.skipif(not WEB.exists(), reason="the web app is not present")


def _sources() -> list[pathlib.Path]:
    return sorted(p for p in WEB.rglob("*.ts*") if p.is_file())


def test_the_frontend_checks_every_word_the_phrasebook_forbids():
    """The two lists must stay in step.

    `web/src/screens/screens.test.tsx` asserts none of these appears in the rendered DOM. If
    somebody adds a word to `language.FORBIDDEN` and not to that list, the frontend
    stops being checked for it silently -- which is exactly how
    `tests/test_language.py`'s hard-coded emitter list let a finding through.
    """
    checked = (WEB / "screens" / "screens.test.tsx").read_text()
    block = checked.split("for (const word of [", 1)
    assert len(block) == 2, "the frontend's code-word check has moved or been removed"
    listed = set(re.findall(r'"([a-z_]+)"', block[1].split("]", 1)[0]))

    missing = sorted(w for w in FORBIDDEN if w not in listed)
    assert not missing, (
        f"web/src/screens/screens.test.tsx does not check for {missing}. Add them there, or the "
        f"frontend is unchecked for vocabulary the phrasebook forbids.")


def test_the_frontend_does_not_hard_code_finding_codes():
    """A finding code in the frontend is a sentence that routed around the phrasebook.

    Every explanation arrives already translated on the row. If a component starts
    branching on `TAINTED_ACCOUNT_NOT_IN_MASTER`, the words for it will be written here
    rather than in `dashboard/language.py`, and there will be two places to audit.
    """
    from dashboard.language import EXPLANATIONS

    # The real codes, not a shape heuristic. An earlier version matched any
    # SCREAMING_CASE token and reported PER_PAGE and URGENCY as finding codes -- a check
    # that cries wolf is a check people learn to override.
    offenders: list[str] = []
    for path in _sources():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith(("*", "//", "/*")):
                continue                          # prose about the rule is not the rule
            for code in EXPLANATIONS:
                if code in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {code}")
    assert not offenders, (
        f"finding codes appear in the frontend: {offenders}. The sentence for a finding "
        f"belongs in dashboard/language.py, which is tested.")


def test_the_frontend_holds_no_invoice_data():
    """DECISIONS #16: no page holds data. A fixture in a component is a stale artifact
    waiting to happen, and it has happened four times in this project."""
    for path in _sources():
        if path.name.endswith(".test.tsx") or path.name.endswith(".test.ts"):
            continue                              # fixtures belong in tests
        text = path.read_text()
        assert "RABO" not in text and "COBA" not in text, f"{path.name} contains an account"
        assert "Meridian" not in text, f"{path.name} contains a supplier name"


def test_severity_is_never_only_a_colour():
    """Roughly one man in twelve has some colour vision deficiency. Every severity must
    reach the screen as words too, which is what the URGENCY table is for."""
    # Screen 03 is where a severity now reaches a person. `Queue.tsx` held this table
    # until the queue was retired with the four-job rebuild; the promise did not move.
    verdict = (WEB / "screens" / "Verdict.tsx").read_text()
    assert "URGENCY" in verdict
    for severity in ("stop", "check"):
        assert re.search(rf'{severity}:\s*\{{\s*word:', verdict), (
            f"severity {severity!r} has no word form; colour would be carrying it alone")
