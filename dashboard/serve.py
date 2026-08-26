"""Serve the review queue: sign in, review, approve.

The approve button posts here, and this runs the actual approval path. There is no
separate demo branch: the same `praetor.gate.approve()` the tests pin is what the browser
hits, and the same `PermissionError` comes back.

Five things have to be true before an approval is written, checked in the order they
matter:

  1. a valid session                      -- who you are is proven, not typed
  2. the approver is not an agent         -- gate.approve(), the architectural invariant
  3. the approver holds `approver` here   -- authorisation, per tenant
  4. the document was escalated to a human -- you cannot approve what nobody asked about
  5. it has not already been approved     -- the schema's primary key

Step 1 is new and it is the point. The approver used to type their own identity into a
text box, so the segregation-of-duties control this project keeps claiming rested on a
self-declaration. The browser can no longer name who it is: the identity comes from the
session, and the request body's opinion is ignored.

    python3 dashboard/serve.py          # then open http://127.0.0.1:8000

Binds to 127.0.0.1 locally. On Cloud Run it binds 0.0.0.0 on $PORT and marks the
session cookie Secure, because Cloud Run terminates TLS in front of the container.

Nothing served here calls a model. The queue reads state and the approve path writes an
approval; adjudication is a separate offline script. So a public deployment cannot burn
API quota or spend money, whoever finds it.
"""
from __future__ import annotations

import html
import json
import os
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor import auth, store  # noqa: E402
from praetor.docile_adapter import load_annotation  # noqa: E402
from praetor.gate import Action, GateDecision, approve  # noqa: E402
from praetor.types import Finding  # noqa: E402

INDEX = ROOT / "dashboard" / "index.html"
COOKIE = "praetor_session"

LOGIN_PAGE = """<!doctype html><meta charset="utf-8">
<title>PRAETOR &mdash; sign in</title>
<style>
:root {{ --bg:#0e1116; --panel:#161b22; --line:#232a34; --tx:#e6edf3; --dim:#8b949e;
        --acc:#58a6ff; --crit:#f85149; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg);
  color:var(--tx); font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:30px 32px; width:392px; }}
h1 {{ margin:0 0 6px; font-size:18px; letter-spacing:-.01em; }}
p.sub {{ margin:0 0 22px; color:var(--dim); font-size:12.5px; line-height:1.5; }}
label {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--dim); margin:14px 0 5px; }}
input {{ width:100%; background:#0b0f14; border:1px solid var(--line); color:var(--tx);
  border-radius:7px; padding:9px 11px; font:13px ui-monospace,Menlo,monospace; }}
input:focus {{ outline:2px solid rgba(88,166,255,.5); outline-offset:1px; }}
button {{ width:100%; margin-top:20px; background:rgba(88,166,255,.16); color:var(--acc);
  border:1px solid rgba(88,166,255,.45); border-radius:7px; padding:9px;
  font:13px inherit; font-weight:600; cursor:pointer; }}
button:hover {{ background:rgba(88,166,255,.26); }}
.err {{ margin-top:16px; color:var(--crit); font-size:12.5px; }}
.seed {{ margin-top:22px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--dim); font-size:11.5px; line-height:1.7; }}
.seed code {{ color:var(--acc); font-family:ui-monospace,Menlo,monospace; }}
</style>
<div class="card">
<h1>PRAETOR</h1>
<p class="sub">Sign in to review the exception queue. Approving a payment records who you
are, so identity is proven here rather than asserted.</p>
<form method="POST" action="/login">
  <label for="email">email</label>
  <input id="email" name="email" autocomplete="username" autofocus value="{email}">
  <label for="password">password</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">Sign in</button>
</form>
{error}
<div class="seed">
  Seeded demo accounts &mdash; password <code>{pw}</code><br>
  <code>reviewer@acme-industries.test</code> &middot; approver<br>
  <code>auditor@acme-industries.test</code> &middot; viewer, cannot approve
</div>
</div>
"""


# Cloud Run gives the container a read-only filesystem in places and charges for CPU
# time, so spawning a Python process per page load -- which is what this did -- is both
# slow and wasteful. Render in-process instead.
def _rebuild(tenant: str, user: str, role: str) -> str:
    from dashboard import build as page

    rows, known = (page.rows_from_db(tenant) if page.store.DB_PATH.exists()
                   or firestore_backend() else page.rows_from_files())
    total = len(rows)
    resolved = [r for r in rows if r["decision"] == "resolve"]
    escalated = [r for r in rows if r["decision"] == "escalate"]
    overrides = [r for r in rows if r["overridden"]]
    wrong = [r for r in resolved if r["correct"] == "escalate"]
    right = [r for r in resolved if r["correct"] == "resolve"]
    prec = len(right) / len(resolved) if resolved else 0.0
    source = f"database &middot; client <b>{tenant}</b>"
    return page.render(rows, total, resolved, escalated, overrides, wrong, prec,
                       source, known, tenant, user, role)


def firestore_backend() -> bool:
    from praetor import firestore_store
    return firestore_store.enabled()


def db():
    """The configured store. serve.py never names a backend directly."""
    from praetor import firestore_store
    return firestore_store if firestore_store.enabled() else store


class Handler(BaseHTTPRequestHandler):
    # ------------------------------------------------------------- plumbing

    def _send(self, code, body: bytes, ctype: str, cookie: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _redirect(self, to: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        jar.load(raw)
        return jar[COOKIE].value if COOKIE in jar else None

    def _login_page(self, code=200, error="", email="") -> None:
        from eval.build_db import DEMO_PASSWORD
        body = LOGIN_PAGE.format(
            error=f'<div class="err">{html.escape(error)}</div>' if error else "",
            email=html.escape(email), pw=DEMO_PASSWORD)
        self._send(code, body.encode(), "text/html; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return {}
        return {k: v[0] for k, v in parse_qs(raw.decode(), keep_blank_values=True).items()}

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        conn = db().connect()

        if path == "/login":
            return self._login_page()
        if path == "/logout":
            auth.end_session(conn, self._token())
            return self._redirect("/login", f"{COOKIE}=; Path=/; Max-Age=0")
        if path == "/document":
            return self._document(conn)
        if path not in ("/", "/index.html"):
            return self._json(404, {"error": "not found"})

        user = auth.session_user(conn, self._token())
        if not user:
            return self._redirect("/login")

        q = parse_qs(urlparse(self.path).query)
        tenant = (q.get("tenant") or [store.DEFAULT_TENANT])[0]
        role = db().role_of(conn, user, tenant)
        if role is None:
            # Signed in, but not a member here. Show a tenant they can actually see.
            mine = [t["id"] for t in db().tenants(conn)
                    if db().role_of(conn, user, t["id"])]
            if not mine:
                return self._json(403, {"error": f"{user} is not a member of any client"})
            return self._redirect(f"/?tenant={mine[0]}")

        try:
            html_page = _rebuild(tenant, user, role)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": "could not build the queue",
                                    "detail": str(e)[-400:]})
        self._send(200, html_page.encode(), "text/html; charset=utf-8")

    def _document(self, conn) -> None:
        """One document, as spans, for the reviewer to look at.

        Scoped twice: the caller must hold a session, and the document must belong to a
        client they are a member of. The file path comes from our own database rather
        than from the query string, and is resolved under the repo root before it is
        opened -- a path from a request is not a path we follow.
        """
        user = auth.session_user(conn, self._token())
        if not user:
            return self._json(401, {"error": "not signed in"})

        q = parse_qs(urlparse(self.path).query)
        tenant = (q.get("tenant") or [store.DEFAULT_TENANT])[0]
        doc_id = (q.get("doc") or [""])[0]

        if db().role_of(conn, user, tenant) is None:
            return self._json(403, {"error": f"{user} is not a member of {tenant}"})

        doc = db().document(conn, tenant, doc_id)
        if doc is None:
            return self._json(404, {"error": f"{doc_id} is not in this client's queue"})

        src = (ROOT / (doc["source_path"] or "")).resolve()
        if not src.is_file() or ROOT not in src.parents:
            return self._json(404, {"error": "source document is not available"})

        annotation, doc_hash = load_annotation(src)
        findings = db().findings_for(conn, tenant, doc_id)
        flagged = {f["span_id"] for f in findings if f["span_id"]}

        spans = []
        for fld in annotation.get("field_extractions", []):
            page = int(fld.get("page", 0))
            bbox = [float(c) for c in fld.get("bbox", [0, 0, 0, 0])]
            sid = f"p{page}:" + "_".join(f"{c:.4f}" for c in bbox)
            spans.append({
                "span_id": sid, "page": page, "bbox": bbox,
                "text": str(fld.get("text", "")).strip(),
                "fieldtype": fld.get("fieldtype"),
                "flagged": sid in flagged,
            })

        return self._json(200, {
            "doc_id": doc_id,
            "doc_hash": doc_hash,
            "stored_hash": doc["doc_hash"],
            "intact": doc_hash == doc["doc_hash"],
            "vendor": doc["vendor_key"],
            "findings": findings,
            "spans": spans,
        })

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        conn = db().connect()

        if path == "/login":
            body = self._body()
            email = str(body.get("email", "")).strip()
            user = auth.authenticate(conn, email, str(body.get("password", "")))
            if not user:
                return self._login_page(401, "That email and password do not match.", email)
            token = auth.start_session(conn, user)
            # Cloud Run terminates TLS in front of the container, so the request arrives
            # over http with the original scheme in a header. Mark the cookie Secure only
            # when the connection really was https, or it will not be sent back locally.
            https = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            secure = " Secure;" if https else ""
            return self._redirect(
                "/", f"{COOKIE}={token}; Path=/; HttpOnly;{secure} SameSite=Strict; "
                     f"Max-Age={auth.SESSION_HOURS * 3600}")

        if path != "/approve":
            return self._json(404, {"error": "not found"})

        # 1. Identity comes from the session. Whatever the body claims is ignored.
        user = auth.session_user(conn, self._token())
        if not user:
            return self._json(401, {"error": "not signed in"})

        body = self._body()
        doc_id = str(body.get("doc_id", ""))
        tenant = str(body.get("tenant") or store.DEFAULT_TENANT)

        rows = [r for r in db().queue(conn, tenant) if r["doc_id"] == doc_id]
        if not rows:
            return self._json(404, {"error": f"{doc_id} is not in this client's queue"})
        row = rows[0]

        decision = GateDecision(
            doc_id=doc_id,
            action=Action.ESCALATE,
            findings=[Finding(f["code"], f["field"], f.get("detail") or "")
                      for f in row["findings"]],
        )

        # 2. The architectural invariant: no agent reaches APPROVED.
        try:
            approved = approve(decision, user)
        except PermissionError as e:
            return self._json(403, {"error": str(e), "refused_id": user})

        # 3. Authorisation. Being a person is necessary, not sufficient.
        role = db().role_of(conn, user, tenant)
        if role != "approver":
            return self._json(403, {
                "error": f"{user} does not hold 'approver' on {tenant}"
                         f" (role: {role or 'none'})", "refused_id": user})

        # 4 and 5. Escalated, and not already approved. Both come from the store.
        try:
            record = db().record_approval(
                conn, tenant, doc_id, approved.approved_by,
                [f.code for f in approved.findings])
        except store.NotEscalated as e:
            return self._json(422, {"error": str(e)})
        except store.AlreadyApproved as e:
            return self._json(409, {"error": str(e)})

        return self._json(200, record)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.command} {urlparse(self.path).path}\n")


def main() -> None:
    # Cloud Run sets $PORT and expects 0.0.0.0. Locally, stay on the loopback.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    host = os.environ.get("PRAETOR_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    conn = db().connect()
    known = [t["id"] for t in db().tenants(conn)]
    if not known:
        # A freshly deployed instance has an empty store. Seed it from the committed
        # results rather than refusing to boot -- Cloud Run health-checks the port, and a
        # container that exits because data is missing never becomes reachable enough to
        # be told about it.
        print("empty store; seeding from results/ ...", flush=True)
        from eval.build_db import DEMO_PASSWORD, load_into, pick
        load_into(db(), conn, store.DEFAULT_TENANT,
                  pick("exc_constructed.jsonl"), pick("adjudication.jsonl"),
                  ROOT / "data/po_register.json")
        known = [t["id"] for t in db().tenants(conn)]
        print(f"seeded {len(known)} client(s); sign in with password {DEMO_PASSWORD}",
              flush=True)
    purged = auth.purge_expired(conn)
    print(f"PRAETOR review queue  ->  http://127.0.0.1:{port}")
    print(f"clients               ->  {', '.join(known)}")
    print(f"database              ->  {store.DB_PATH}")
    if purged:
        print(f"expired sessions purged: {purged}")
    print(f"listening on {host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
