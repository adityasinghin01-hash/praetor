"""Derived artifacts must match the corpus they claim to describe.

This defect has now happened three times, each time silently, each time discovered by
someone reading a number rather than by anything failing:

1. `out/exc_constructed.jsonl` was left over from a 300-invoice run and scored against a
   350-invoice truth set, producing an F1 that did not reproduce and a dashboard showing
   no reason for 23 of 65 rows. (FINDINGS §5, first correction.)
2. The corpus was regenerated on 27 Aug and the committed `dashboard/index.html` kept
   serving span ids from the single-layout corpus.
3. `out/praetor.db` was built before that regeneration, so rebuilding the page from the
   database reproduced the stale ids even after the page itself was regenerated.

The common shape: an artifact derived from the corpus outlives the corpus, and nothing
notices, because a stale artifact renders perfectly. It just describes a document that no
longer exists.

So the rule is a test. A span id is a coordinate, so an id that is not in the corpus is
proof that whatever produced it was looking at different documents.

If this fails, nothing is broken — something is out of date. Rebuild the chain:

    make corpus && make rules && make db && make dashboard
"""
import json
import pathlib
import re
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "constructed"
SPAN = re.compile(r"p\d+:[0-9]+\.[0-9]+_[0-9.]+_[0-9.]+_[0-9.]+")

pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="no corpus generated")


def _live_span_ids() -> set[str]:
    """Every span id the current corpus can legitimately produce."""
    out = set()
    for p in CORPUS.glob("*.json"):
        for f in json.loads(p.read_text()).get("field_extractions", []):
            bbox = f.get("bbox") or [0, 0, 0, 0]
            out.add(f"p{int(f.get('page', 0))}:" + "_".join(f"{c:.4f}" for c in bbox))
    return out


def _report(name: str, found: set[str], live: set[str]) -> None:
    stale = found - live
    assert not stale, (
        f"{name} references {len(stale)} span ids that are not in the corpus "
        f"(e.g. {sorted(stale)[:3]}). It was built from different documents. "
        f"Rebuild: make corpus && make rules && make db && make dashboard")


def test_the_committed_dashboard_matches_the_corpus():
    """The page is checked in so a judge can open it without running anything. That
    convenience is only worth having while the page is true."""
    page = ROOT / "dashboard" / "index.html"
    if not page.exists():
        pytest.skip("dashboard not built")
    found = set(SPAN.findall(page.read_text()))
    assert found, "the page shows no evidence at all, which is its own bug"
    _report("dashboard/index.html", found, _live_span_ids())


def test_the_exceptions_file_matches_the_corpus():
    """The file that scores the rules baseline. This is the one that broke first."""
    for rel in ("out/exc_constructed.jsonl", "results/exc_constructed.jsonl"):
        p = ROOT / rel
        if not p.exists():
            continue
        found = set()
        for line in p.read_text().splitlines():
            if line.strip():
                found |= set(SPAN.findall(line))
        if found:
            _report(rel, found, _live_span_ids())


def test_the_database_matches_the_corpus():
    db = ROOT / "out" / "praetor.db"
    if not db.exists():
        pytest.skip("no database built")
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT span_id FROM findings WHERE span_id IS NOT NULL").fetchall()
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    except sqlite3.DatabaseError:
        pytest.skip("database predates the findings table")
    finally:
        conn.close()

    # An empty database is not a clean one. This test used to pass on a database with no
    # rows at all, which is exactly the state a half-finished rebuild leaves behind --
    # and the dashboard renders an empty queue from it without complaining. "No stale
    # data" and "no data" must not look the same to a test.
    assert documents > 0, (
        "out/praetor.db exists but holds no documents. Something clobbered it. "
        "Rebuild: make db")

    found = {r[0] for r in rows if r[0]}
    assert found, "the database holds documents but no evidence, which is its own bug"
    _report("out/praetor.db", found, _live_span_ids())


def test_the_truth_file_covers_exactly_the_corpus():
    """A truth set and a corpus of different sizes is how the first correction happened."""
    truth = ROOT / "data" / "constructed_truth.jsonl"
    if not truth.exists():
        pytest.skip("no truth file")
    ids = {json.loads(line)["doc_id"] for line in truth.read_text().splitlines()
           if line.strip()}
    docs = {p.stem for p in CORPUS.glob("*.json")}
    assert ids == docs, (
        f"truth set and corpus disagree: {len(ids - docs)} scored documents do not "
        f"exist, {len(docs - ids)} documents are unscored. Rebuild: make corpus")
