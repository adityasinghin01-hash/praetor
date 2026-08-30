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
# Account creation hashes a password and writes identity state, so it receives a tighter
# bound than ordinary POSTs. It is separate from sign-in so one flow cannot starve the
# other during a demo.
SIGNUP_LIMIT = ratelimit.RateLimiter(limit=5, window=3600.0, global_limit=50)

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

# Authentication is intentionally rendered server-side: nobody receives the React
# application until their session is valid. These braces are doubled because the page is
# formatted with escaped values below.
AUTH_STYLES = """
:root {{ --night:#050816; --panel:#0c1226; --panel-2:#121a35; --text:#f7f8ff;
  --muted:#9ca9c8; --violet:#8b5cf6; --cyan:#22d3ee; --green:#34d399;
  --danger:#fb7185; --line:rgba(148,163,184,.2); --ui:"Geist Variable",Inter,system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; color:var(--text); font:1rem/1.55 var(--ui);
  background:radial-gradient(circle at 12% 12%,rgba(139,92,246,.23),transparent 32rem),
    radial-gradient(circle at 88% 82%,rgba(34,211,238,.14),transparent 30rem),var(--night); }}
body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.22;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
  background-size:48px 48px; mask-image:linear-gradient(to bottom,black,transparent 86%); }}
.auth-shell {{ position:relative; min-height:100vh; display:grid; grid-template-columns:minmax(0,1.15fr) minmax(22rem,.85fr);
  align-items:center; gap:clamp(2rem,7vw,7rem); width:min(76rem,100%); margin:auto;
  padding:clamp(1.25rem,4vw,4rem); }}
.eyebrow {{ margin:0 0 1.25rem; color:var(--cyan); font:700 .72rem/1 var(--mono);
  letter-spacing:.18em; text-transform:uppercase; }}
.brand {{ margin:0; font-size:clamp(3.4rem,9vw,7rem); line-height:.82; letter-spacing:-.07em;
  background:linear-gradient(110deg,#fff 18%,#c4b5fd 55%,#67e8f9); color:transparent;
  background-clip:text; -webkit-background-clip:text; }}
.hero h2 {{ max-width:14ch; margin:1.4rem 0 1rem; font-size:clamp(1.45rem,3vw,2.35rem); line-height:1.12; }}
.hero-copy {{ max-width:37rem; color:var(--muted); font-size:1.04rem; }}
.pipeline {{ display:flex; flex-wrap:wrap; align-items:center; gap:.55rem; margin-top:2rem;
  color:var(--muted); font:650 .72rem/1.3 var(--mono); letter-spacing:.05em; text-transform:uppercase; }}
.pipeline b {{ color:var(--text); border:1px solid var(--line); background:rgba(12,18,38,.7);
  padding:.58rem .7rem; border-radius:.55rem; }}
.pipeline i {{ color:var(--cyan); font-style:normal; }}
.proof {{ display:grid; grid-template-columns:repeat(3,1fr); gap:.65rem; margin-top:1rem; max-width:38rem; }}
.proof span {{ min-height:4.8rem; padding:.8rem; border:1px solid var(--line); border-radius:.8rem;
  background:rgba(12,18,38,.6); color:var(--muted); font-size:.78rem; }}
.proof strong {{ display:block; color:var(--text); font-size:1rem; margin-bottom:.15rem; }}
.card {{ position:relative; padding:clamp(1.4rem,4vw,2.25rem); border:1px solid var(--line);
  border-radius:1.3rem; background:linear-gradient(145deg,rgba(18,26,53,.96),rgba(8,13,29,.94));
  box-shadow:0 28px 90px rgba(0,0,0,.38),inset 0 1px rgba(255,255,255,.05); backdrop-filter:blur(18px); }}
.card::before {{ content:""; position:absolute; inset:-1px; border-radius:inherit; padding:1px;
  background:linear-gradient(130deg,rgba(139,92,246,.8),transparent 36%,rgba(34,211,238,.55));
  mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  mask-composite:exclude; pointer-events:none; }}
.status {{ display:inline-flex; align-items:center; gap:.45rem; color:var(--green);
  font:700 .7rem/1 var(--mono); letter-spacing:.12em; text-transform:uppercase; }}
.status::before {{ content:""; width:.48rem; height:.48rem; border-radius:50%; background:var(--green);
  box-shadow:0 0 14px var(--green); }}
.card h2 {{ margin:.8rem 0 .25rem; font-size:1.65rem; }}
.sub {{ margin:0 0 1.55rem; color:var(--muted); font-size:.9rem; }}
label {{ display:block; margin:1rem 0 .38rem; color:#cbd5e1; font-size:.78rem; font-weight:650; }}
input {{ width:100%; border:1px solid var(--line); border-radius:.7rem; padding:.78rem .85rem;
  background:rgba(2,6,23,.55); color:var(--text); font:inherit; }}
input:focus {{ outline:2px solid var(--cyan); outline-offset:2px; border-color:transparent; }}
button,.primary-link {{ display:flex; justify-content:center; width:100%; margin-top:1.25rem;
  border:0; border-radius:.72rem; padding:.82rem 1rem; color:white; font:750 .94rem var(--ui);
  text-decoration:none; cursor:pointer; background:linear-gradient(105deg,var(--violet),#6d5ce7 48%,#0891b2);
  box-shadow:0 10px 28px rgba(109,92,231,.28); transition:transform .18s,filter .18s; }}
button:hover,.primary-link:hover {{ transform:translateY(-1px); filter:brightness(1.08); }}
button:focus-visible,.primary-link:focus-visible,.text-link:focus-visible {{ outline:3px solid var(--cyan); outline-offset:3px; }}
.switch {{ margin:1.25rem 0 0; text-align:center; color:var(--muted); font-size:.86rem; }}
.text-link {{ color:#a5f3fc; font-weight:700; text-decoration:none; }}
.text-link:hover {{ text-decoration:underline; }}
.err {{ margin-top:1rem; padding:.7rem .8rem; border:1px solid rgba(251,113,133,.35);
  border-radius:.65rem; background:rgba(251,113,133,.09); color:#fecdd3; font-size:.84rem; }}
.seed {{ margin-top:1.2rem; padding-top:1rem; border-top:1px solid var(--line); color:var(--muted);
  font-size:.75rem; line-height:1.7; }}
.seed code {{ color:#d8b4fe; font-family:var(--mono); }}
.guardrail {{ margin-top:1rem; display:flex; gap:.55rem; color:var(--muted); font-size:.76rem; }}
.guardrail strong {{ color:var(--green); }}
@media (max-width:52rem) {{ .auth-shell {{ grid-template-columns:1fr; }} .hero {{ padding-top:2rem; }}
  .brand {{ font-size:clamp(3rem,16vw,5.5rem); }} .proof {{ display:none; }} }}
@media (max-width:30rem) {{ .auth-shell {{ padding:1rem; }} .pipeline {{ display:none; }} .card {{ border-radius:1rem; }} }}
@media (prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto!important; transition:none!important; }} }}
"""

LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>PRAETOR &mdash; secure sign in</title>
<meta name="viewport" content="width=device-width,initial-scale=1">{fonts}
<style>""" + AUTH_STYLES + """</style></head><body>
<main class="auth-shell">
  <section class="hero" aria-labelledby="brand-title">
    <p class="eyebrow">Autonomous AP · deterministic control</p>
    <h1 class="brand" id="brand-title">PRAETOR</h1>
    <h2>Let the agent read hostile invoices. Never let them control the payment.</h2>
    <p class="hero-copy">PRAETOR converts model output into traceable references, resolves
    values deterministically, and keeps sensitive actions behind policy and human identity.</p>
    <div class="pipeline" aria-label="Security pipeline"><b>Untrusted document</b><i>→</i>
      <b>Span references</b><i>→</i><b>Policy gate</b><i>→</i><b>Human approval</b></div>
    <div class="proof"><span><strong>Provenance</strong>Every value points back to evidence</span>
      <span><strong>Least privilege</strong>Agents cannot approve payments</span>
      <span><strong>Cloud native</strong>Gemini + Google Cloud</span></div>
  </section>
  <section class="card" aria-labelledby="form-title">
    <span class="status">Control plane online</span>
    <h2 id="form-title">Welcome back</h2>
    <p class="sub">Sign in with your verified identity to enter the review console.</p>
    <form method="POST" action="/login">
      <label for="email">Work email</label>
      <input id="email" name="email" type="email" autocomplete="username"
             value="{email}" required{emailfocus}>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password"
             value="{password}" required>
      <button type="submit"{focus}>Enter secure console →</button>
    </form>
    {error}
    <p class="switch">New to PRAETOR? <a class="text-link" href="/signup">Create a viewer account</a></p>
    <p class="guardrail"><strong>●</strong> Signup never grants payment approval.</p>
    {seed}
  </section>
</main></body></html>"""

SIGNUP_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>PRAETOR &mdash; create account</title>
<meta name="viewport" content="width=device-width,initial-scale=1">{fonts}
<style>""" + AUTH_STYLES + """</style></head><body>
<main class="auth-shell">
  <section class="hero" aria-labelledby="brand-title">
    <p class="eyebrow">Explore the secured workflow</p>
    <h1 class="brand" id="brand-title">PRAETOR</h1>
    <h2>A front-row seat to an agent that knows where its authority ends.</h2>
    <p class="hero-copy">Your account receives viewer access to synthetic demo data. You can
    inspect evidence, provenance, attacks, and agent decisions—but payment approval remains
    restricted to identities granted the approver role by an administrator.</p>
    <div class="pipeline"><b>Viewer by default</b><i>→</i><b>No self-escalation</b><i>→</i>
      <b>Server-enforced roles</b></div>
  </section>
  <section class="card" aria-labelledby="form-title">
    <span class="status">Least privilege enforced</span>
    <h2 id="form-title">Create viewer account</h2>
    <p class="sub">Explore the synthetic PRAETOR demo without gaining approval authority.</p>
    <form method="POST" action="/signup">
      <label for="name">Name</label>
      <input id="name" name="name" autocomplete="name" maxlength="80" value="{name}" required autofocus>
      <label for="email">Work email</label>
      <input id="email" name="email" type="email" autocomplete="username" maxlength="254"
             value="{email}" required>
      <label for="password">Password · 12 characters minimum</label>
      <input id="password" name="password" type="password" autocomplete="new-password"
             minlength="12" maxlength="128" required>
      <label for="confirm">Confirm password</label>
      <input id="confirm" name="confirm" type="password" autocomplete="new-password"
             minlength="12" maxlength="128" required>
      <button type="submit">Create secure viewer account →</button>
    </form>
    {error}
    <p class="switch">Already have access? <a class="text-link" href="/login">Sign in</a></p>
    <p class="guardrail"><strong>●</strong> Approver access is never available through signup.</p>
  </section>
</main></body></html>"""


def prefill(email: str = "") -> dict:
    """What the sign-in form arrives holding.

    Off a deployed URL the fields are filled and the caret sits on the button, so signing
    in is one keypress. That is the same trade DECISIONS #11 already made for the seed
    block, and it is gated the same way: a credential typed into the page next to the
    form it opens is fine on your own machine and indefensible on a public URL, however
    synthetic the invoices behind it are.

    A failed attempt keeps whatever was typed. Overwriting somebody's own email with the
    demo one, mid-correction, would be its own small cruelty.
    """
    if deployed() or email:
        return {"email": email, "password": "",
                "emailfocus": " autofocus", "focus": ""}
    from eval.build_db import DEMO_PASSWORD

    return {"email": "reviewer@acme-industries.test", "password": DEMO_PASSWORD,
            "emailfocus": "", "focus": " autofocus"}


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
        filled = prefill(email)
        body = LOGIN_PAGE.format(
            error=f'<div class="err">{html.escape(error)}</div>' if error else "",
            email=html.escape(filled["email"]),
            password=html.escape(filled["password"]),
            emailfocus=filled["emailfocus"], focus=filled["focus"],
            seed=seed, fonts="")
        self._send(code, body.encode(), "text/html; charset=utf-8")

    def _signup_page(self, code=200, error="", name="", email="") -> None:
        body = SIGNUP_PAGE.format(
            error=f'<div class="err" role="alert">{html.escape(error)}</div>'
                  if error else "",
            name=html.escape(name), email=html.escape(email), fonts="")
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
        if path == "/signup":
            return self._signup_page()
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

        if path == "/signup":
            if not self._allowed(SIGNUP_LIMIT):
                return None
            body = self._body()
            name = str(body.get("name", "")).strip()
            email = str(body.get("email", "")).strip()
            password = str(body.get("password", ""))
            if password != str(body.get("confirm", "")):
                return self._signup_page(400, "Passwords do not match.", name, email)
            try:
                user = auth.register_viewer(
                    conn, email, name, password, store.DEFAULT_TENANT)
            except auth.RegistrationError as exc:
                return self._signup_page(400, str(exc), name, email)
            token = auth.start_session(conn, user)
            https = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            secure = " Secure;" if https else ""
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
