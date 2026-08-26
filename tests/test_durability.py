"""Durability and the spending ceiling, expressed as tests.

The bug these exist to prevent: out/spend.json was written with write_text(), which
truncates before it writes. A crash in that window left a truncated file, _load()
swallowed the parse error and returned a zero Spend, and the ceiling reset to "nothing
spent". The one control protecting a billing account failed open.
"""
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from praetor import costguard
from praetor.durable import append_line, locked, write_atomic, write_json_atomic


# ---------------------------------------------------------------- atomic writes

def test_write_atomic_replaces_whole_file(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    write_json_atomic(p, {"a": 2})
    assert json.loads(p.read_text())["a"] == 2


def test_write_atomic_leaves_no_temp_files(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_a_failed_write_leaves_the_old_file_intact(tmp_path, monkeypatch):
    """The property the ceiling depends on: never a half-written ledger.

    The failure is injected at the rename, which is the last step — so the new content
    is fully on disk and the swap is what fails. The reader must still see the old file,
    whole, and no temp file may be left lying around pretending to be a ledger.
    """
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})

    def boom(*_args, **_kwargs):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_atomic(p, '{"a": 2}')

    assert json.loads(p.read_text())["a"] == 1
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_append_line_writes_whole_records(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(5):
        append_line(p, json.dumps({"i": i}))
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [r["i"] for r in rows] == [0, 1, 2, 3, 4]


def _appender(args):
    path, start = args
    for i in range(start, start + 25):
        append_line(path, json.dumps({"i": i}))


def test_concurrent_appends_do_not_interleave(tmp_path):
    """An audit trail for payments must not corrupt when two processes write at once."""
    p = tmp_path / "approvals.jsonl"
    with multiprocessing.Pool(4) as pool:
        pool.map(_appender, [(str(p), s) for s in (0, 100, 200, 300)])

    lines = [l for l in p.read_text().splitlines() if l.strip()]
    assert len(lines) == 100
    for line in lines:
        json.loads(line)          # every line is a whole, parseable record


def test_locked_does_not_truncate_the_file_it_protects(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    with locked(p):
        assert json.loads(p.read_text())["a"] == 1


# ---------------------------------------------------------------- the ceiling

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "spend.json"
    monkeypatch.setattr(costguard, "SPEND_FILE", path)
    return path


def test_a_missing_ledger_means_zero_spent(ledger):
    assert costguard._load().usd == 0.0


def test_a_corrupt_ledger_refuses_to_spend(ledger):
    """The regression. Damaged file used to read as zero and hand back the ceiling."""
    ledger.write_text('{"usd": 0.5, "calls": 3')      # truncated mid-write
    with pytest.raises(costguard.CorruptSpendFile):
        costguard._load()
    with pytest.raises(costguard.CorruptSpendFile):
        costguard.check("gemini-3.5-flash", 4000)


def test_a_corrupt_ledger_is_reported_not_hidden(ledger):
    ledger.write_text("not json at all")
    assert "UNREADABLE" in costguard.report()


def test_recording_accumulates(ledger):
    costguard.record("gemini-3.5-flash-lite", 1000, 100)
    costguard.record("gemini-3.5-flash-lite", 1000, 100)
    s = costguard._load()
    assert s.calls == 2
    assert s.input_tokens == 2000


def test_the_ceiling_actually_refuses(ledger, monkeypatch):
    monkeypatch.setattr(costguard, "CEILING_INR", 0.01)
    with pytest.raises(costguard.BudgetExceeded):
        costguard.check("gemini-3.5-flash", 400_000)


def _recorder(path):
    from praetor import costguard as cg
    cg.SPEND_FILE = Path(path)
    for _ in range(20):
        cg.record("gemini-3.5-flash-lite", 100, 10)


def test_concurrent_recording_loses_nothing(ledger):
    """Read-modify-write without a lock silently undercounts exactly when it matters."""
    with multiprocessing.Pool(4) as pool:
        pool.map(_recorder, [str(ledger)] * 4)
    assert costguard._load().calls == 80


def test_the_ledger_survives_a_kill_mid_write(ledger):
    """Simulates the original crash: a temp file left behind must not become the ledger."""
    costguard.record("gemini-3.5-flash-lite", 500, 50)
    before = costguard._load().calls
    (ledger.parent / f".{ledger.name}.orphan.tmp").write_text("{ truncated")
    assert costguard._load().calls == before
    os.remove(ledger.parent / f".{ledger.name}.orphan.tmp")
