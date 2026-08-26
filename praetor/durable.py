"""Writes that survive a crash, and a lock that survives concurrency.

This file exists because of a specific failure. `out/spend.json` is the only thing
standing between this project and a billing account carrying a dunning flag, and it was
written with `Path.write_text()` — which truncates first and writes second. A crash in
that window leaves a truncated file; `costguard._load()` swallowed the parse error and
returned a zero `Spend`; and the ceiling silently reset to "nothing spent". The one
control protecting the money failed open.

The same shape of bug, with lower stakes, applies to the approvals log: a plain append
from two processes can interleave mid-line and corrupt an audit trail for payments.

So: every whole-file write goes through `write_atomic`, every read-modify-write cycle
goes through `locked`, and every append goes through `append_line`. No LLM in this file,
and nothing here knows what an invoice is.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    """A rename is only durable once the directory entry itself is flushed."""
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path: str | Path, data: str) -> None:
    """Write to a temp file in the same directory, fsync it, then rename over the target.

    rename(2) is atomic within a filesystem, so a reader sees either the whole old file
    or the whole new one — never a half-written one. That is the property the spend
    ceiling depends on.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_atomic(path: str | Path, obj) -> None:
    write_atomic(path, json.dumps(obj, indent=1) + "\n")


@contextmanager
def locked(path: str | Path):
    """Hold an exclusive lock for a read-modify-write cycle on `path`.

    The lock lives in a sidecar file, so taking it never truncates the thing being
    protected — a lock that damages its subject on acquisition is worse than none.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def append_line(path: str | Path, line: str) -> None:
    """Append one record durably and under lock, so concurrent writers cannot interleave."""
    path = Path(path)
    with locked(path):
        with open(path, "a") as fh:
            fh.write(line.rstrip("\n") + "\n")
            fh.flush()
            os.fsync(fh.fileno())
