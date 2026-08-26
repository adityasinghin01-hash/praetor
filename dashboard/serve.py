"""Serve the review queue and handle real approvals.

The dashboard was read-only, which meant the single most important act in the whole
design — a human approving a payment — existed only as a function and a test. Nobody
could see it happen.

This makes it real. The approve button posts here, and this calls the actual
`praetor.gate.approve()`. There is no separate demo path: the same PermissionError that
protects the system in `tests/test_invariants.py` is what the browser gets back if you
try to approve as an agent. That is worth seeing rather than being told.

Approvals append to out/approvals.jsonl, so the audit trail is a file you can read.

    python3 dashboard/serve.py          # then open http://127.0.0.1:8000

Local only, single user, no auth: this is a demonstration of the boundary, not a
production console. Binding to 127.0.0.1 is deliberate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor.gate import Action, GateDecision, approve  # noqa: E402
from praetor.types import Finding  # noqa: E402

APPROVALS = ROOT / "out" / "approvals.jsonl"
INDEX = ROOT / "dashboard" / "index.html"


def _exceptions() -> dict:
    for name in ("out/exc_constructed.jsonl", "results/exc_constructed.jsonl"):
        p = ROOT / name
        if p.exists():
            return {json.loads(l)["doc_id"]: json.loads(l)
                    for l in p.read_text().splitlines() if l.strip()}
    return {}


def _rebuild() -> None:
    subprocess.run([sys.executable, str(ROOT / "dashboard" / "build.py")],
                   cwd=ROOT, check=True, capture_output=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] not in ("/", "/index.html"):
            return self._json(404, {"error": "not found"})
        _rebuild()
        self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/approve":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad request"})

        doc_id = str(body.get("doc_id", ""))
        human_id = str(body.get("human_id", ""))

        row = _exceptions().get(doc_id)
        if not row:
            return self._json(404, {"error": f"unknown document {doc_id}"})

        decision = GateDecision(
            doc_id=doc_id,
            action=Action.ESCALATE,
            findings=[Finding(f["code"], f["field"], f["detail"])
                      for f in row.get("findings", [])],
        )

        try:
            # The real thing. Not a demo branch — this is the same call the tests pin.
            approved = approve(decision, human_id)
        except PermissionError as e:
            return self._json(403, {"error": str(e), "refused_id": human_id})

        APPROVALS.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "doc_id": approved.doc_id,
            "action": approved.action.value,
            "approved_by": approved.approved_by,
            "codes": [f.code for f in approved.findings],
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with APPROVALS.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        return self._json(200, record)

    def log_message(self, fmt, *args):  # quieter console during a demo
        sys.stderr.write(f"  {self.command} {self.path}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    _rebuild()
    print(f"PRAETOR review queue  ->  http://127.0.0.1:{port}")
    print(f"approvals append to   ->  {APPROVALS}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
