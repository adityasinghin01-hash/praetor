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

from dashboard import api, build, gauntlet, ratelimit  # noqa: E402

# One limiter per process. The expensive public endpoint is the one that
# runs the pipeline and writes to disk; the read-only ones are cheap but
# still worth bounding, so they share a looser limiter.
RUN_LIMIT = ratelimit.RateLimiter(limit=20, window=60.0, global_limit=120)
# Sign-in is the one place a stranger can guess at something valuable. PBKDF2 makes each
# guess expensive for us as well as for them, so an unmetered login form is both a
# brute-force surface and a way to burn our CPU.
LOGIN_LIMIT = ratelimit.RateLimiter(limit=10, window=300.0, global_limit=60)

# Headers every response carries.
#
# `frame-ancestors 'none'` and X-Frame-Options are not boilerplate here: this app has an
# Approve button that moves money, and clickjacking it is a real attack rather than a
# theoretical one.
#
# The CSP allows inline script and style, which is weaker than it should be, because the
# app is a single self-contained file. Every value rendered goes through textContent, so
# there is no HTML-injection path today -- but this is a known compromise, not a
# considered win, and it goes away when the pages are split into real assets.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"),
}
# Reads per caller per minute. Overridable so `eval/run_load.py` can measure capacity
# rather than measuring this limiter -- with the default in force a load test just proves
# the limiter refuses, which is worth knowing and is not a throughput number.
#
# The default is the shipped value. Raising it is an explicit act on one process.
READ_LIMIT = ratelimit.RateLimiter(
    limit=int(os.environ.get("PRAETOR_READ_LIMIT", "120")),
    window=60.0,
    global_limit=int(os.environ.get("PRAETOR_READ_LIMIT_GLOBAL", "600")))

INDEX = ROOT / "dashboard" / "index.html"
COOKIE = "praetor_session"

LOGIN_PAGE = """<!doctype html><meta charset="utf-8">
<title>PRAETOR &mdash; sign in</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{fonts}
<style>
/* The door to the app, in the app's own direction: ink on paper, one seal red, three
   line weights, nothing rounded. Written inline and standalone on purpose -- this page
   is served by the stdlib transport too, where there is no build and no stylesheet to
   link. `{{fonts}}` is where the deployed transport injects the real faces; without it
   the fallbacks below carry it, which is the difference between right and wrong-ish,
   not between working and broken. */
:root {{
  --paper:#EFEEE8; --paper-2:#E7E5DC; --ink:#0B0B0B; --ink-2:#2A2926;
  --ink-3:#6E6C63; --seal:#BE2B22;
  --w-hair:1px; --w-mid:1.5px; --w-heavy:2.5px;
  --display:"Shippori Mincho B1","Yu Mincho",Georgia,serif;
  --ui:"Zen Kaku Gothic New","Hiragino Sans",ui-sans-serif,-apple-system,sans-serif;
  --mono:ui-monospace,Menlo,Consolas,monospace;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:1.5rem;
  background:var(--paper); color:var(--ink); font:0.95rem/1.6 var(--ui); }}
.card {{ background:var(--paper); border:var(--w-heavy) solid var(--ink);
  padding:2rem 2.1rem 2.2rem; width:min(26rem,100%); }}
h1 {{ margin:0 0 .2rem; font-family:var(--display); font-weight:800; font-size:1.9rem;
  letter-spacing:.02em; }}
p.sub {{ margin:0 0 1.6rem; color:var(--ink-2); font-size:.88rem; max-width:30ch; }}
label {{ display:block; font-size:.7rem; text-transform:uppercase; letter-spacing:.12em;
  color:var(--ink-3); font-weight:700; margin:1.1rem 0 .3rem; }}
/* A ruled line, not a box. The same input the key rail uses inside the app. */
input {{ width:100%; background:none; border:0; border-bottom:var(--w-mid) solid var(--ink);
  color:var(--ink); padding:.35rem 0; font:0.95rem var(--mono); }}
input:focus {{ outline:none; border-bottom-color:var(--seal); }}
button {{ width:100%; margin-top:1.6rem; background:var(--paper); color:var(--ink);
  border:var(--w-mid) solid var(--ink); border-bottom-width:var(--w-heavy);
  border-right-width:var(--w-heavy); box-shadow:3px 3px 0 var(--ink);
  padding:.6rem; font:700 0.95rem var(--ui); cursor:pointer;
  transition:translate .07s, box-shadow .07s; }}
button:active {{ translate:3px 3px; box-shadow:0 0 0 var(--ink); }}
button:focus-visible {{ outline:3px solid var(--seal); outline-offset:3px; }}
.err {{ margin-top:1.1rem; padding-left:.8rem; border-left:3px solid var(--seal);
  color:var(--seal); font-size:.85rem; }}
.seed {{ margin-top:1.6rem; padding-top:1rem; border-top:var(--w-hair) solid rgba(11,11,11,.2);
  color:var(--ink-3); font-size:.78rem; line-height:1.8; }}
.seed code {{ color:var(--ink); font-family:var(--mono); }}
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
{seed}
</div>
"""

# DECISIONS.md #11 prints the demo password on the sign-in page on purpose: a judge who
# clones the repo has no other way in, and that is worth more than the secrecy of a
# password to a throwaway database of synthetic invoices.
#
# It is worth more *locally*. On a public URL it is just a credential printed next to the
# form it opens, which is indefensible however synthetic the data is. Cloud Run sets
# K_SERVICE, so the block appears when someone runs the repo and disappears when it is
# deployed -- the ADR's intent kept, without the part that only made sense offline.
SEED_BLOCK = """<div class="seed">
  Seeded demo accounts &mdash; password <code>{pw}</code><br>
  <code>reviewer@acme-industries.test</code> &middot; approver<br>
  <code>auditor@acme-industries.test</code> &middot; viewer, cannot approve
</div>"""


def deployed() -> bool:
    """True when running on Cloud Run rather than on someone's machine."""
    return bool(os.environ.get("K_SERVICE"))


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

    def _send(self, code, body: bytes, ctype: str, cookie: str | None = None,
              cache: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _too_many(self, retry_after: int) -> None:
        """Plain language, and a Retry-After a client can actually obey."""
        body = json.dumps({
            "error": "Too many attempts from here. Wait a moment and try again.",
            "retry_after_seconds": retry_after,
        }).encode()
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", str(retry_after))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self, limiter) -> bool:
        key = ratelimit.caller_key(self.headers, self.client_address)
        ok, retry = limiter.check(key)
        if not ok:
            self._too_many(retry)
        return ok

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json",
                   cache="no-store")

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
        seed = ""
        if not deployed():
            from eval.build_db import DEMO_PASSWORD
            seed = SEED_BLOCK.format(pw=html.escape(DEMO_PASSWORD))
        body = LOGIN_PAGE.format(
            error=f'<div class="err">{html.escape(error)}</div>' if error else "",
            email=html.escape(email), seed=seed, fonts="")
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

    # ------------------------------------------------------------------ the JSON API
    #
    # The pages hold no data. They fetch from here, and here reads the pipeline's own
    # output on every request. A page with data baked into it has gone stale twice in
    # this project (FINDINGS §5, and again on 27 Aug); this is the fix that makes it
    # structurally impossible rather than something to remember.

    def _rows(self, conn, tenant: str):
        """Queue rows from the database when there is one, from files otherwise, so
        `make demo` works with no database at all."""
        if store.DB_PATH.exists() or firestore_backend():
            rows, _ = build.rows_from_db(tenant)
        else:
            rows, _ = build.rows_from_files()
        return rows

    def _api_get(self, conn, path: str, q: dict) -> None:
        # Tab 3 is deliberately open: it is the "try to break it" page, it touches only
        # the synthetic corpus, and requiring a login to attack a demo defeats its point.
        if path.startswith("/v1/gauntlet/") and not self._allowed(READ_LIMIT):
            return None
        if path == "/v1/gauntlet/documents":
            return self._json(200, api.gauntlet_documents())
        # Open, and it must stay open: the page asks it before anything else to find out
        # whether there is a session, so that a visitor with none is shown the tab that
        # works for them instead of a sign-in form. It existed on the FastAPI transport
        # and not on this one, which is the asymmetry `test_both_transports_return_the_
        # same_json` exists to prevent.
        if path == "/v1/field-labels":
            return self._json(200, api.field_labels())

        if path == "/v1/health":
            who = auth.session_user(conn, self._token())
            tenant = (q.get("tenant") or [store.DEFAULT_TENANT])[0] if who else None
            role = db().role_of(conn, who, tenant) if who else None
            return self._json(200, api.health(bool(who), who, role,
                                              tenant if role else None))

        if path == "/v1/gauntlet/placements":
            return self._json(200, api.gauntlet_placements())

        if path == "/v1/gauntlet/examples":
            return self._json(200, api.gauntlet_examples())
        if path == "/v1/gauntlet/document":
            try:
                return self._json(200, api.gauntlet_document((q.get("id") or [""])[0]))
            except KeyError:
                return self._json(404, {"error": "no such invoice"})

        # Everything below is a client's own data and needs a session.
        user = auth.session_user(conn, self._token())
        if not user:
            return self._json(401, {"error": "not signed in"})
        tenant = (q.get("tenant") or [store.DEFAULT_TENANT])[0]
        if db().role_of(conn, user, tenant) is None:
            return self._json(403, {"error": "not a member of this client"})

        if path == "/v1/queue":
            return self._json(200, api.queue(self._rows(conn, tenant)))
        if path == "/v1/stopped":
            return self._json(200, api.stopped(self._rows(conn, tenant)))
        if path == "/v1/cleared":
            return self._json(200, api.cleared(self._rows(conn, tenant)))
        if path == "/v1/notes":
            doc_id = (q.get("doc_id") or [""])[0]
            return self._json(200, {"notes": store.notes_for(conn, tenant, doc_id)})
        return self._json(404, {"error": "not found"})

    def _api_post(self, conn, path: str, body: dict) -> None:
        if path == "/v1/gauntlet/run":
            # The only anonymous endpoint that does real work and writes to disk.
            if not self._allowed(RUN_LIMIT):
                return None
            try:
                return self._json(200, api.gauntlet_run(
                    str(body.get("doc_id", "")), str(body.get("text", "")),
                    str(body.get("placement", "") or gauntlet.DEFAULT_PLACEMENT)))
            except KeyError:
                return self._json(404, {"error": "no such invoice"})

        user = auth.session_user(conn, self._token())
        if not user:
            return self._json(401, {"error": "not signed in"})
        tenant = str(body.get("tenant") or store.DEFAULT_TENANT)
        if db().role_of(conn, user, tenant) is None:
            return self._json(403, {"error": "not a member of this client"})

        if path == "/v1/notes":
            # The author is the session, never the body. Same rule as approval:
            # a self-declared identity is not an identity. See DECISIONS.md #11.
            try:
                return self._json(200, store.add_note(
                    conn, tenant, str(body.get("doc_id", "")), user,
                    str(body.get("body", "")), str(body.get("kind", "note"))))
            except ValueError as e:
                return self._json(422, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        conn = db().connect()

        if path.startswith("/v1/"):
            return self._api_get(conn, path, parse_qs(urlparse(self.path).query))
        if path == "/app":
            # Read from disk every time and tell the browser never to cache it. A
            # cached page showing yesterday's queue is the same defect class as a
            # committed page showing yesterday's corpus, and it is worse here because
            # the person looking at it has no way to tell.
            page = (Path(__file__).resolve().parent / "app.html").read_bytes()
            return self._send(200, page, "text/html; charset=utf-8",
                              cache="no-store, must-revalidate")

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

        if path.startswith("/v1/"):
            return self._api_post(conn, path, self._body())

        if path == "/login":
            if not self._allowed(LOGIN_LIMIT):
                return None
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
            # To /app, not /. `/` is the older single-page queue and has no tabs, so
            # signing in landed people on a page missing two thirds of the product --
            # including the one page anybody sent a link is there to use. Watching
            # somebody hunt for the "try to break it" button is how this was found.
            return self._redirect(
                "/app", f"{COOKIE}={token}; Path=/; HttpOnly;{secure} SameSite=Strict; "
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

    def version_string(self) -> str:
        """Do not advertise the interpreter version to everyone who asks."""
        return "PRAETOR"

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
