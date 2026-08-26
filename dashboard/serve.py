"""Serve the review queue and handle real approvals.

The approve button posts here, and this runs the actual approval path. There is no
separate demo branch: the same `praetor.gate.approve()` the tests pin is what the browser
hits, and the same `PermissionError` comes back.

Four things have to be true before an approval is written, and they are checked in this
order because that is the order in which they matter:

  1. the approver is not an agent          -- gate.approve(), the architectural invariant
  2. the approver holds `approver` on this tenant  -- authorisation
  3. the document was actually escalated to a human -- you cannot approve what nobody asked
  4. the document has not already been approved     -- enforced by the schema's primary key

Approvals land in SQLite. A duplicate is a constraint violation rather than a second row,
so idempotency is a property of the database instead of something a handler remembers.

    python3 dashboard/serve.py          # then open http://127.0.0.1:8000

Local only, and there is still no login: `human_id` is asserted, not proven. Roles are
enforced, identity is not. That gap is the next piece of work, and it is stated in the
README rather than papered over.
"""
from __future__ import annotations

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor import store  # noqa: E402
from praetor.gate import Action, GateDecision, approve  # noqa: E402
from praetor.types import Finding  # noqa: E402

INDEX = ROOT / "dashboard" / "index.html"


def _rebuild(tenant: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "dashboard" / "build.py"),
                    "--tenant", tenant],
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

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            return self._json(404, {"error": "not found"})
        q = parse_qs(parsed.query)
        tenant = (q.get("tenant") or [store.DEFAULT_TENANT])[0]
        try:
            _rebuild(tenant)
        except subprocess.CalledProcessError as e:
            return self._json(500, {"error": "could not build the queue",
                                    "detail": e.stderr.decode()[-400:]})
        self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/approve":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad request"})

        doc_id = str(body.get("doc_id", ""))
        human_id = str(body.get("human_id", ""))
        tenant = str(body.get("tenant") or store.DEFAULT_TENANT)

        conn = store.connect()
        rows = [r for r in store.queue(conn, tenant) if r["doc_id"] == doc_id]
        if not rows:
            return self._json(404, {"error": f"{doc_id} is not in this tenant's queue"})
        row = rows[0]

        decision = GateDecision(
            doc_id=doc_id,
            action=Action.ESCALATE,
            findings=[Finding(f["code"], f["field"], f.get("detail") or "")
                      for f in row["findings"]],
        )

        # 1. The architectural invariant. An agent has no route to APPROVED, and this is
        #    the same call tests/test_invariants.py pins.
        try:
            approved = approve(decision, human_id)
        except PermissionError as e:
            return self._json(403, {"error": str(e), "refused_id": human_id})

        # 2. Authorisation. Being a person is necessary, not sufficient.
        role = store.role_of(conn, human_id, tenant)
        if role != "approver":
            return self._json(403, {
                "error": f"{human_id} does not hold 'approver' on {tenant}"
                         f" (role: {role or 'none'})",
                "refused_id": human_id})

        # 3 and 4. Escalated, and not already approved. Both refusals come from the store.
        try:
            record = store.record_approval(
                conn, tenant, doc_id, approved.approved_by,
                [f.code for f in approved.findings])
        except store.NotEscalated as e:
            return self._json(422, {"error": str(e)})
        except store.AlreadyApproved as e:
            return self._json(409, {"error": str(e)})

        return self._json(200, record)

    def log_message(self, fmt, *args):  # quieter console during a demo
        sys.stderr.write(f"  {self.command} {self.path}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    conn = store.connect()
    known = [t["id"] for t in store.tenants(conn)]
    if not known:
        sys.exit("No tenants in the database. Run:  python3 eval/build_db.py")
    _rebuild(known[0])
    print(f"PRAETOR review queue  ->  http://127.0.0.1:{port}")
    print(f"tenants               ->  {', '.join(known)}")
    print(f"database              ->  {store.DB_PATH}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
