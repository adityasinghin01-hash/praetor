"""Tracing, with the taint label riding on every span.

The architecture has claimed since the first draft that "OTel spans carry taint labels
throughout", and until now no tracing code existed. This is that claim, implemented.

What makes it worth having is not the timing data. It is that a span records *where a
value came from* -- its document hash, its span id, and whether it is tainted -- so the
provenance of anything that reached a payment is auditable after the fact, from a trace
rather than from a log line someone remembered to write.

Deliberately exported to a local file. Cloud Trace is the eventual destination and
swapping to it is one exporter, but a trace you can only read after a deployment is a
trace you cannot use while building. `make trace` prints one document's spans.

OpenTelemetry is an optional dependency. Without it every function here becomes a no-op
so the pipeline and `make demo` still run -- a missing tracer must never be the reason
an invoice fails to process.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_FILE = ROOT / "out" / "trace.jsonl"

try:  # pragma: no cover - exercised by whether the package is installed
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

# We hold our own provider rather than installing a global one. OpenTelemetry refuses to
# override a global TracerProvider once set, which makes a process that configures twice
# -- a test suite, or a long-running server that switches trace files -- silently keep
# writing to the first destination.
_provider = None


if AVAILABLE:
    class _JsonlExporter(SpanExporter):
        """Write finished spans to a JSONL file.

        ConsoleSpanExporter writes to stdout, which would bury the numbers the eval
        scripts print. A file keeps the trace and the report separate.
        """

        def __init__(self, path: Path):
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)

        def export(self, spans) -> "SpanExportResult":
            with self.path.open("a") as fh:
                for s in spans:
                    ctx = s.get_span_context()
                    fh.write(json.dumps({
                        "name": s.name,
                        "trace_id": f"{ctx.trace_id:032x}",
                        "span_id": f"{ctx.span_id:016x}",
                        "parent": (f"{s.parent.span_id:016x}" if s.parent else None),
                        "start": s.start_time,
                        "duration_us": (s.end_time - s.start_time) // 1000,
                        "status": s.status.status_code.name,
                        "attributes": dict(s.attributes or {}),
                    }) + "\n")
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None


def configure(path: str | Path | None = None, force: bool = False) -> bool:
    """Start tracing to a file. Returns whether tracing is actually on."""
    global _provider
    if not AVAILABLE:
        return False
    if _provider is not None and not force:
        return True
    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(_JsonlExporter(Path(path) if path else TRACE_FILE)))
    _provider = provider
    return True


def enabled() -> bool:
    """Tracing is off unless asked for, so a plain run stays quiet and fast."""
    return AVAILABLE and (os.environ.get("PRAETOR_TRACE", "").lower()
                          in ("1", "true", "yes", "on"))


@contextmanager
def span(name: str, **attributes):
    """A span, or nothing at all if tracing is off. Never changes what the caller does."""
    if not enabled():
        yield _Null()
        return
    configure()
    tracer = _provider.get_tracer("praetor")
    with tracer.start_as_current_span(name) as s:
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(k, v)
        yield s


class _Null:
    """Stands in for a span when tracing is off, so call sites need no branches."""

    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


def taint(field) -> dict:
    """The attributes that make a span say where a value came from.

    This is the part that matters. `praetor.tainted` on a span is how you answer, months
    later, whether a paid value originated in a document nobody trusted.
    """
    if field is None:
        return {"praetor.present": False}
    prov = getattr(field, "prov", None)
    if prov is None:
        return {"praetor.present": True, "praetor.tainted": False}
    return {
        "praetor.present": True,
        "praetor.tainted": bool(prov.tainted),
        "praetor.doc_hash": prov.doc_hash,
        "praetor.span_id": prov.span_id or "",
    }


def read(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else TRACE_FILE
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
