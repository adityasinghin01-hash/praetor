"""The frozen corpus must survive every change to the generator that made it.

`data/constructed` is what every published figure in FINDINGS.md is scored against. The
generator has since grown line items, multi-page documents, three account formats and
non-English notes -- all optional, all defaulting off. If any of them leaks into the
default path, the corpus changes, and a changed corpus does not announce itself: the
numbers simply drift and nobody knows which run they came from.

This regenerates it with default arguments and compares bytes.

The failure mode being guarded is specific and has happened here before. Adding layouts
on 27 Aug took extra draws from the shared random stream and silently re-planted the
corpus -- 54 deviations became 57, at different documents, and the F1 that came back was
a different random draw wearing the old number's clothes. Every capability added since
takes its draws from a stream of its own for that reason.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "constructed"


def digest_of(directory: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in sorted(directory.glob("*.json")):
        h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    if not CORPUS.exists():
        pytest.skip("data/constructed not present")
    out = tmp_path_factory.mktemp("corpus") / "constructed"
    r = subprocess.run(
        [sys.executable, "eval/make_invoices.py", "--out", str(out), "--per-vendor", "14"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-900:]
    return out


def test_the_frozen_corpus_regenerates_byte_for_byte(regenerated):
    assert digest_of(regenerated) == digest_of(CORPUS), (
        "data/constructed changed. Every number in FINDINGS.md is scored against it, so "
        "either a default in eval/make_invoices.py moved, or a new option is drawing from "
        "the content random stream when it is switched off.")


def test_the_ground_truth_regenerates_too(regenerated):
    got = (regenerated.parent / "constructed_truth.jsonl").read_bytes()
    assert hashlib.sha256(got).hexdigest() == \
        hashlib.sha256((ROOT / "data" / "constructed_truth.jsonl").read_bytes()).hexdigest()


def test_the_new_capabilities_are_off_by_default(regenerated):
    """Teeth. If line items or a second page appear without being asked for, the test
    above would fail for a reason nobody could read off the hash."""
    for p in sorted(regenerated.glob("*.json"))[:40]:
        ann = json.loads(p.read_text())
        assert "pages" not in ann, f"{p.name} records a page count it should not"
        for span in ann["field_extractions"]:
            assert span["line_item_id"] is None, f"{p.name} has line items"
            assert span["page"] == 0, f"{p.name} has a second page"


def test_a_second_corpus_cannot_overwrite_the_first_ones_ground_truth(tmp_path):
    """The generator used to write `constructed_truth.jsonl` into the PARENT directory,
    so generating any second corpus into data/ would have destroyed the frozen corpus's
    ground truth in place. Sidecar names are derived from the corpus directory now."""
    out = tmp_path / "somethingelse"
    r = subprocess.run(
        [sys.executable, "eval/make_invoices.py", "--out", str(out),
         "--vendors", "3", "--per-vendor", "4"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-900:]
    assert (tmp_path / "somethingelse_truth.jsonl").exists()
    assert not (tmp_path / "constructed_truth.jsonl").exists()
    assert not (tmp_path / "po_register.json").exists()


def test_the_three_account_formats_are_actually_three_shapes(tmp_path):
    """A benchmark of one account shape bakes in one answer -- FINDINGS §28 measured Path
    B scoring 125 of 125 on the shape it was fitted on and 0 of 216 on the other two."""
    sys.path.insert(0, str(ROOT))
    from eval.make_invoices import ACCOUNT_FORMATS, _account
    import random

    got = {f: _account(f, random.Random(1)) for f in ACCOUNT_FORMATS}
    assert any(c.isalpha() for c in got["iban"])
    assert got["indian"].isdigit(), got["indian"]
    assert not any(c.isalpha() for c in got["uk"]) and "-" in got["uk"], got["uk"]
    assert len({v for v in got.values()}) == 3


def test_the_authority_rule_is_english_only_and_that_is_recorded():
    """Pinned deliberately. `praetor/authority.py` recognises an approval claim with an
    English regular expression; FINDINGS §28 measures German, Dutch and French all
    failing. The failure is in the safe direction -- an unrecognised claim authorises
    nothing -- but a legitimate non-English approval is equally invisible.

    If somebody localises it, this test fails and §28 has to be rewritten rather than
    quietly becoming untrue.
    """
    sys.path.insert(0, str(ROOT))
    from praetor.authority import APPROVAL_LANGUAGE

    assert APPROVAL_LANGUAGE.search("approved under PO PO-68910")
    for text in ("genehmigt gemaess Bestellung PO-68910",
                 "goedgekeurd onder inkooporder PO-68910",
                 "approuves selon le bon de commande PO-68910"):
        assert not APPROVAL_LANGUAGE.search(text), (
            "authority.py now recognises a non-English approval claim. That is an "
            "improvement -- update FINDINGS §28, which says it does not.")
