"""Secrets come from the environment in production, never off the filesystem.

A deployed service that reads a credential from its own disk means the key was baked into
an image or written to a volume: it outlives the process, it is in a layer somebody can
pull, and it is invisible to the audit trail Secret Manager keeps. The ingest service is
given `GOOGLE_API_KEY` from Secret Manager at start, so a missing variable should fail
loudly rather than send the process looking around the disk.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from praetor.agents import reader

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_environment_wins(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "from-the-environment")
    assert reader._api_key() == "from-the-environment"


def test_production_refuses_to_read_a_key_off_the_disk(monkeypatch, tmp_path):
    """The whole point. On Cloud Run there is no legitimate reason for a key to be in a
    file, so finding one there is a reason to stop rather than to continue."""
    planted = tmp_path / ".env"
    planted.write_text("GOOGLE_API_KEY=should-never-be-read\n")

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("K_SERVICE", "praetor-ingest")
    monkeypatch.setattr(reader, "ENV_FILES", (planted,))

    with pytest.raises(SystemExit) as excinfo:
        reader._api_key()

    message = str(excinfo.value)
    assert "Secret Manager" in message
    assert "should-never-be-read" not in message, "the refusal leaked the key it refused"


def test_a_laptop_still_falls_back_so_the_demo_runs(monkeypatch, tmp_path):
    """Without this, `make demo` needs somebody to export a variable first."""
    planted = tmp_path / ".env"
    planted.write_text("GOOGLE_API_KEY=from-a-file\n")

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(reader, "ENV_FILES", (planted,))

    assert reader._api_key() == "from-a-file"


def test_a_laptop_with_nothing_anywhere_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(reader, "ENV_FILES", (tmp_path / "absent.env",))

    with pytest.raises(SystemExit, match="No GOOGLE_API_KEY"):
        reader._api_key()


def test_no_credential_literal_is_committed():
    """Belt and braces: a key pasted into a file is the failure this whole rule exists
    to prevent, so the tree is scanned for one."""
    pattern = re.compile(r"AQ\.[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,}")
    skip = {".venv", "node_modules", "dist", ".git", "out"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in skip for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".tf", ".json", ".yaml", ".yml", ".ts", ".tsx", ".html"}:
            continue
        assert not pattern.search(path.read_text(errors="ignore")), f"credential in {path}"
