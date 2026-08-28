"""The test count printed in the documents must be the test count that exists.

Six documents quote it — README, TEAMMATE, SUBMISSION twice over, the architecture
diagram. It has gone stale three times in two days, every time because somebody (me) added
tests and did not chase every file. It is a small lie each time, and it sits directly
beside the numbers that matter, which is what makes it worth automating rather than
remembering.

The count is read from the live session, so this cannot drift: add a test and this one
fails until the documents say so.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Files that quote the number, and the shapes they quote it in.
DOCUMENTS = ["README.md", "TEAMMATE.md", "docs/SUBMISSION.md", "docs/architecture.html",
             "docs/PLAN.md"]
CLAIM = re.compile(
    r"(\d{2,5})\s*(?:passing tests|tests pass|tests hold|tests are|passed`|tests</span>)")


def _claims() -> list[tuple[str, int, str]]:
    out = []
    for rel in DOCUMENTS:
        p = ROOT / rel
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            for m in CLAIM.finditer(line):
                out.append((rel, int(m.group(1)), line.strip()[:90]))
    return out


def test_the_documents_quote_the_real_test_count(request):
    """Skips unless the whole suite is being collected, so running one file is fine."""
    collected = request.session.testscollected
    if collected < 100:
        pytest.skip("partial run; this check only means anything on the full suite")

    claims = _claims()
    assert claims, (
        "no document quotes a test count any more. If that was deliberate, delete this "
        "test; if not, the claim has been lost.")

    wrong = [(f, n, line) for f, n, line in claims if n != collected]
    assert not wrong, (
        f"the suite has {collected} tests; these say otherwise:\n" +
        "\n".join(f"  {f}: {n}  ->  {line}" for f, n, line in wrong))


def test_the_claim_pattern_actually_matches_something():
    """Teeth. The test above passes vacuously if the regex stops matching after a
    rewording, which is exactly when it would be needed."""
    found = {f for f, _, _ in _claims()}
    assert len(found) >= 3, f"only found claims in {found}; the pattern has rotted"
