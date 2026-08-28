"""Every attack anyone types, kept — because the corpus is the part nobody can clone.

The architecture in this repo is copyable in a quarter. The measurements are copyable the
moment they are published. What is not copyable is a growing collection of **real
invoice-injection attempts by real people**, each labelled with exactly which checks it
got past, because nobody else is running a page that invites them.

That is the Gandalf lesson, applied to a domain nobody has applied it to. Lakera made a
game, collected attacks at scale, and the corpus — not the guardrail — was the asset. No
equivalent exists for document extraction: FINDINGS §3 established that no public
benchmark even measures this threat model, which means every attempt logged here is data
that does not exist anywhere else.

The honest limits, and they belong in the file rather than only in a slide:

* **This is instrumentation, not a dataset.** Until real people use it for months, it is
  an empty table with a good schema. `docs/ROADMAP.md` says describe the pipes, never
  claim the water, and a judge will know the difference.
* **`beat` is the valuable column, not the text.** A payload that beat four checks is
  worth more than a thousand that beat none, and the shape of that distribution is the
  actual finding.

Append-only JSONL. One line per attempt, written whole, so a crash mid-write cannot
corrupt earlier entries. Standard library only.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "out" / "attack_corpus.jsonl"

MAX_TEXT = 2000       # a payload, not an essay
_MAX_BYTES = 32 * 1024 * 1024


def record(text: str, doc_id: str, steps_passed: list[str], stopped_at: int | None,
           stopped: bool, source: str = "web", path: Path | None = None) -> dict:
    """Log one attempt. Never raises: losing a log line must not break the page."""
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "text": (text or "")[:MAX_TEXT],
        "chars": len(text or ""),
        "doc_id": doc_id,
        "beat": list(steps_passed),      # the column that matters
        "depth": len(steps_passed),
        "stopped": bool(stopped),
        "stopped_at": stopped_at,
        "source": source,
    }
    p = Path(path) if path else DEFAULT_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > _MAX_BYTES:
            return entry                 # full; drop rather than fill the disk
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        # One append of one short line, flushed and fsynced: a reader never sees half.
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:  # noqa: BLE001
        # Deliberately broad, and the only place in this repo that should be.
        # The contract is that logging cannot break the page, and the failure modes are
        # not all OSError -- a bad path raises ValueError, a surprising `path` argument
        # raises TypeError. Narrowing this to the errors we happened to think of is how
        # a logging call ends up returning a 500 to someone trying the demo.
        # Nothing security-critical runs here: this is a write-only record kept after
        # the decision has already been made.
        pass
    return entry


def load(path: Path | None = None) -> list[dict]:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue                     # a torn final line never kills the read
    return out


def summary(path: Path | None = None) -> dict:
    """What the corpus knows so far. Shaped for a counter on the page."""
    rows = load(path)
    depths = Counter(r.get("depth", 0) for r in rows)
    got_through = [r for r in rows if not r.get("stopped")]
    deepest = max((r.get("depth", 0) for r in rows), default=0)
    return {
        "attempts": len(rows),
        "distinct": len({(r.get("text") or "").strip().lower() for r in rows}),
        "stopped": sum(1 for r in rows if r.get("stopped")),
        "got_through": len(got_through),
        "deepest": deepest,
        "by_depth": {str(k): depths[k] for k in sorted(depths)},
        "hardest": sorted(rows, key=lambda r: -r.get("depth", 0))[:5],
    }
