"""Where a field sits must not change what the document says.

On 27 Aug the generator gained five layouts and per-document bbox jitter. Both are
wanted -- a one-layout corpus flatters anything position-aware. But `jittered()` drew
its four uniforms per field from the *same* stream that rolls deviations, so every
document's geometry shifted the next document's content. The corpus was silently
re-planted: 54 deviations became 57, at different documents.

No rule in `praetor/baseline_rules.py` reads a coordinate. So the F1 that came back
(0.874 -> 0.908) was not the rules getting better on a harder corpus -- it was a
different random draw wearing the old number's clothes. That is the kind of number
that survives into a submission and cannot be defended when someone asks how it moved.

The fix is a separate jitter stream, seeded per document. These tests pin it, and they
are written so they fail if the streams are ever merged again.
"""
import json
import sys

import pytest

from eval import make_invoices

VENDORS, PER_VENDOR = 4, 8


def _generate(tmp_path, monkeypatch, *, jitter: bool, seed: int = 7):
    """Build a small corpus and return (truth rows, {doc_id: annotation}).

    With `jitter=False`, `jittered()` becomes a no-op that draws *nothing*. That is the
    discriminating case: if geometry and content share a stream, removing the draws
    moves the content, and the comparison below fails.
    """
    out = tmp_path / ("jittered" if jitter else "flat")
    with monkeypatch.context() as m:
        if not jitter:
            m.setattr(make_invoices, "jittered", lambda bbox, rng: list(bbox))
        m.setattr(sys, "argv", ["make_invoices", "--out", str(out),
                                "--vendors", str(VENDORS),
                                "--per-vendor", str(PER_VENDOR),
                                "--seed", str(seed)])
        make_invoices.main()
    rows = [json.loads(line) for line in
            (out.parent / "constructed_truth.jsonl").read_text().splitlines()]
    docs = {p.stem: json.loads(p.read_text()) for p in out.glob("*.json")}
    return rows, docs


def _texts(annotation: dict) -> list[tuple[str, str]]:
    return [(f["fieldtype"], f["text"]) for f in annotation["field_extractions"]]


def _boxes(annotation: dict) -> list[list[float]]:
    return [f["bbox"] for f in annotation["field_extractions"]]


def test_jitter_cannot_move_content(tmp_path, monkeypatch):
    """The whole point: turning jitter off must not change a single planted deviation."""
    jittered_rows, jittered_docs = _generate(tmp_path, monkeypatch, jitter=True)
    flat_rows, flat_docs = _generate(tmp_path, monkeypatch, jitter=False)

    assert jittered_rows == flat_rows
    assert set(jittered_docs) == set(flat_docs)
    for doc_id, annotation in jittered_docs.items():
        assert _texts(annotation) == _texts(flat_docs[doc_id]), doc_id


def test_jitter_actually_moves_the_boxes(tmp_path, monkeypatch):
    """Teeth for the test above, which would otherwise pass if jitter did nothing."""
    jittered_docs = _generate(tmp_path, monkeypatch, jitter=True)[1]
    flat_docs = _generate(tmp_path, monkeypatch, jitter=False)[1]

    moved = sum(1 for d, a in jittered_docs.items()
                if _boxes(a) != _boxes(flat_docs[d]))
    assert moved == len(jittered_docs)


def test_jitter_is_reproducible(tmp_path, monkeypatch):
    """Seeded per document, so the corpus regenerates bit-for-bit -- coordinates too."""
    first = _generate(tmp_path / "a", monkeypatch, jitter=True)[1]
    second = _generate(tmp_path / "b", monkeypatch, jitter=True)[1]

    assert first == second


def test_each_document_gets_its_own_geometry(tmp_path, monkeypatch):
    """An exact-coordinate lookup must not be a shortcut past the reader."""
    docs = _generate(tmp_path, monkeypatch, jitter=True)[1]

    ibans = [tuple(f["bbox"]) for a in docs.values()
             for f in a["field_extractions"] if f["fieldtype"] == "payment_iban"]
    assert len(ibans) > 1
    assert len(set(ibans)) == len(ibans)
