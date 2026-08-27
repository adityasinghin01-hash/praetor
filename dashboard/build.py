"""Build the review dashboard from real result files.

This is what appears in the demo video: the queue a human actually works. It reads the
adjudication results, the rules findings and the ground truth, and renders a single
self-contained HTML file with no external dependencies.

Four things on this page are not decoration:

  * Every flagged value carries its provenance — TAINTED, the span it came from, the
    hash of the document it came from. A person approving a payment can see that the
    figure they are approving was lifted off an untrusted document, and exactly where.
  * The approve control posts to dashboard/serve.py, which calls the real
    praetor.gate.approve(). Approving as an agent returns the real PermissionError.
  * The audit view (`u`, or click any outcome badge) replays one document through the
    pipeline stage by stage. It renders only what the store actually holds — no stage
    is narrated from an assumption.
  * Filtering, search and keyboard navigation run client-side against data embedded in
    the page, so they work in `make demo` with no server at all.

Every number comes from a results file. Nothing is hardcoded.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor import store  # noqa: E402

# Ordered worst-first, so the codes a reviewer most wants to isolate sit leftmost
# rather than wherever a Counter happened to put them.
CODE_ORDER = [
    "BANK_UNKNOWN",
    "DUPLICATE_INVOICE",
    "AMOUNT_OUT_OF_RANGE",
    "TAX_RATE_MISMATCH",
    "CURRENCY_MISMATCH",
    "ADDRESS_MISMATCH",
    "MISSING_FIELD",
]


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def result(name: str) -> Path:
    """A fresh run in out/ wins; results/ is the committed measurement it falls back to."""
    fresh = ROOT / "out" / name
    return fresh if fresh.exists() else ROOT / "results" / name


def backend():
    """Whichever store is configured. Everything below is written against one shape.

    Cloud Run has an ephemeral filesystem, so a SQLite file there would vanish on every
    cold start. PRAETOR_BACKEND=firestore is what makes a deployed instance keep state.
    """
    from praetor import firestore_store
    return firestore_store if firestore_store.enabled() else store


def rows_from_db(tenant: str) -> tuple[list[dict], list[str]]:
    """Live state. The database is what the queue actually serves from."""
    truth = {r["doc_id"]: r for r in load_jsonl(ROOT / "data/constructed_truth.jsonl")}
    db = backend()
    conn = db.connect()
    known = [t["id"] for t in db.tenants(conn)]
    rows = []
    for r in db.queue(conn, tenant):
        t = truth.get(r["doc_id"], {})
        evidence = {f["field"]: {"value": f["value"], "span_id": f["span_id"],
                                 "doc_hash": (r["doc_hash"] or "")[:12],
                                 "tainted": bool(f["tainted"])}
                    for f in r["findings"] if f["value"]}
        rows.append({
            "doc_id": r["doc_id"],
            "vendor": r["vendor_key"] or "?",
            "peers": r["peer_invoices"] or 0,
            "codes": [f["code"] for f in r["findings"]],
            "findings": [{"code": f["code"], "field": f["field"],
                          "detail": f["detail"] or ""} for f in r["findings"]],
            "evidence": evidence,
            "decision": r["decision"],
            "agent_decision": r["agent_decision"],
            "overridden": bool(r["overridden"]),
            "override_reason": r["override_reason"],
            "reason": r["reason"] or "",
            "correct": t.get("correct_action", "?"),
            "injected": bool(t.get("injected")),
            "approved_by": r["approved_by"],
            "approved_at": r.get("approved_at"),
            "model": r.get("model"),
            "doc_hash": r.get("doc_hash") or "",
        })
    return rows, known


def rows_from_files() -> tuple[list[dict], list[str]]:
    """No database yet. `make demo` must still produce a full queue from files alone."""
    truth = {r["doc_id"]: r for r in load_jsonl(ROOT / "data/constructed_truth.jsonl")}
    adj = {}
    for r in load_jsonl(result("adjudication.jsonl")):
        adj.setdefault(r["doc_id"], r)
    exceptions = {r["doc_id"]: r for r in load_jsonl(result("exc_constructed.jsonl"))}

    rows = []
    for doc_id, a in sorted(adj.items()):
        t = truth.get(doc_id, {})
        e = exceptions.get(doc_id, {})
        evidence = e.get("evidence", {})
        # In file mode the only hash on hand is the truncated one carried per value.
        # Take it rather than leave the audit view with a blank it cannot explain.
        any_hash = next((v.get("doc_hash", "") for v in evidence.values()), "")
        rows.append({
            "doc_id": doc_id,
            "vendor": e.get("vendor_key", "?"),
            "peers": e.get("n_peer_invoices", 0),
            "codes": a.get("codes", []),
            "findings": e.get("findings", []),
            "evidence": evidence,
            "decision": a["decision"],
            "agent_decision": a["agent_decision"],
            "overridden": a["overridden"],
            "override_reason": a.get("override_reason"),
            "reason": a.get("reason", ""),
            "correct": t.get("correct_action", "?"),
            "injected": bool(t.get("injected")),
            "approved_by": None,
            "approved_at": None,
            "model": a.get("model"),
            "doc_hash": any_hash,
        })
    return rows, []


def clip(text: str, n: int) -> str:
    """Truncate on a word boundary. Cutting mid-word reads as a rendering fault."""
    text = (text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    space = cut.rfind(" ")
    return (cut[:space] if space > n * 0.6 else cut).rstrip(" ,.;:") + "\u2026"


def outcome_of(r: dict) -> str:
    """One label per row, most consequential first. Drives both badge and filter."""
    if r.get("approved_by"):
        return "approved"
    if r["overridden"]:
        return "override"
    return "cleared" if r["decision"] == "resolve" else "escalated"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=store.DEFAULT_TENANT)
    ap.add_argument("--user", default="")
    ap.add_argument("--role", default="")
    args = ap.parse_args()

    if store.DB_PATH.exists():
        rows, known = rows_from_db(args.tenant)
        source = f"database &middot; tenant <b>{args.tenant}</b>"
    else:
        rows, known = rows_from_files()
        source = "results files (no database yet &mdash; run <code>eval/build_db.py</code>)"

    total = len(rows)
    resolved = [r for r in rows if r["decision"] == "resolve"]
    escalated = [r for r in rows if r["decision"] == "escalate"]
    overrides = [r for r in rows if r["overridden"]]
    wrong = [r for r in resolved if r["correct"] == "escalate"]
    right = [r for r in resolved if r["correct"] == "resolve"]
    prec = len(right) / len(resolved) if resolved else 0.0

    out = ROOT / "dashboard" / "index.html"
    out.write_text(render(rows, total, resolved, escalated, overrides, wrong, prec,
                          source, known, args.tenant, args.user, args.role))
    print(f"wrote {out}")
    print(f"  {total} exceptions | {len(resolved)} resolved | {len(escalated)} escalated "
          f"| {len(overrides)} gate override(s) | precision {prec:.3f}")


# --------------------------------------------------------------------------- styles

CSS = """
:root { --bg:#0e1116; --panel:#161b22; --line:#232a34; --tx:#e6edf3; --dim:#8b949e;
        --good:#3fb950; --warn:#d29922; --crit:#f85149; --acc:#58a6ff; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--tx);
  font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }
header { padding:26px 32px 18px; border-bottom:1px solid var(--line); }
h1 { margin:0; font-size:19px; letter-spacing:-.01em; }
header p { margin:6px 0 0; color:var(--dim); font-size:13px; max-width:900px; }
.who { margin-top:12px; font-size:12.5px; color:var(--dim); }
.who select { background:#0b0f14; border:1px solid var(--line); color:var(--tx);
  border-radius:6px; padding:5px 9px; font:12.5px ui-monospace,Menlo,monospace;
  margin-left:6px; }
.who .me { font-family:ui-monospace,Menlo,monospace; color:var(--tx); }
.who .role { margin-left:7px; padding:2px 8px; border-radius:20px; font-size:11px;
  background:rgba(88,166,255,.14); color:var(--acc); }
.who .out { color:var(--dim); }
.stats { display:flex; gap:14px; padding:22px 32px 16px; flex-wrap:wrap; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; min-width:158px; flex:1; }
.card .v { font-size:27px; font-weight:600; letter-spacing:-.02em; }
.card .l { color:var(--dim); font-size:12px; text-transform:uppercase;
  letter-spacing:.06em; margin-top:4px; }
.card .s, td .s { color:var(--dim); font-size:11.5px; margin-top:3px; }
.card.good .v { color:var(--good); } .card.warn .v { color:var(--warn); }
.card.crit .v { color:var(--crit); }

/* ------------------------------------------------------------------ controls */
.controls { padding:4px 32px 14px; display:flex; flex-direction:column; gap:11px; }
.crow { display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
.search { position:relative; flex:1; min-width:280px; max-width:520px; }
.search input { width:100%; background:#0b0f14; border:1px solid var(--line);
  color:var(--tx); border-radius:8px; padding:9px 12px 9px 32px;
  font:13px ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }
.search input:focus { outline:2px solid rgba(88,166,255,.5); outline-offset:1px;
  border-color:transparent; }
.search .mag { position:absolute; left:11px; top:50%; transform:translateY(-50%);
  color:var(--dim); font-size:13px; pointer-events:none; }
.shown { color:var(--dim); font-size:12.5px; font-family:ui-monospace,Menlo,monospace;
  white-space:nowrap; }
.shown b { color:var(--tx); }
.hint { color:var(--dim); font-size:12px; margin-left:auto; }
.hint kbd { font:11px ui-monospace,Menlo,monospace; background:#21262d;
  border:1px solid var(--line); border-bottom-width:2px; border-radius:4px;
  padding:1px 5px; color:#c9d1d9; }
.chips { display:flex; gap:7px; flex-wrap:wrap; align-items:center; }
.chips .lbl { color:var(--dim); font-size:10.5px; text-transform:uppercase;
  letter-spacing:.07em; margin-right:3px; min-width:58px; }
.chip { background:#0b0f14; border:1px solid var(--line); color:var(--dim);
  border-radius:20px; padding:4px 11px; font:11.5px ui-monospace,Menlo,monospace;
  cursor:pointer; user-select:none; white-space:nowrap; }
.chip:hover { border-color:#3d4757; color:var(--tx); }
.chip .n { opacity:.65; margin-left:5px; }
.chip.on { background:rgba(88,166,255,.16); border-color:rgba(88,166,255,.5);
  color:var(--acc); }
.chip.on.crit { background:rgba(248,81,73,.16); border-color:rgba(248,81,73,.5);
  color:var(--crit); }
.chip.on.good { background:rgba(63,185,80,.14); border-color:rgba(63,185,80,.45);
  color:var(--good); }
.chip.on.warn { background:rgba(210,153,34,.16); border-color:rgba(210,153,34,.5);
  color:var(--warn); }
.chip.zero { opacity:.38; }
.chip.clear { border-style:dashed; }

/* --------------------------------------------------------------------- table */
table { width:calc(100% - 64px); margin:0 32px 40px; border-collapse:collapse;
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  overflow:hidden; }
th { text-align:left; padding:11px 14px; font-size:11px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--dim); border-bottom:1px solid var(--line); }
td { padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:top; }
tr:last-child td { border-bottom:none; }
tbody tr.sel td { background:rgba(88,166,255,.07); }
tbody tr.sel td:first-child { box-shadow:inset 3px 0 0 var(--acc); }
tr.gone { display:none; }
#empty { display:none; padding:34px; text-align:center; color:var(--dim);
  font-size:13px; }
#empty.on { display:block; }
.b { display:inline-block; padding:2px 8px; border-radius:20px; font-size:11px;
  background:#21262d; color:var(--dim); white-space:nowrap; border:1px solid transparent;
  cursor:pointer; }
.b:hover { border-color:#3d4757; }
.b.good { background:rgba(63,185,80,.14); color:var(--good); }
.b.warn { background:rgba(210,153,34,.14); color:var(--warn); cursor:default; }
.b.crit { background:rgba(248,81,73,.16); color:var(--crit); font-weight:600; }
.code { font-family:ui-monospace,monospace; font-size:11px; background:#21262d;
  padding:2px 6px; border-radius:4px; color:#c9d1d9; margin-right:4px; }
.d { font-family:ui-monospace,monospace; font-size:10.5px; color:var(--dim); }
.reason { color:var(--dim); font-size:12.5px; max-width:300px; }
.prov { margin-bottom:7px; }
.t { display:inline-block; font-size:9.5px; font-weight:700; letter-spacing:.07em;
  padding:1px 5px; border-radius:3px; background:rgba(248,81,73,.16); color:var(--crit);
  vertical-align:middle; }
.t.ok { background:rgba(63,185,80,.14); color:var(--good); }
.pv { font-family:ui-monospace,Menlo,monospace; font-size:12px; margin-left:7px; }
.ps { font-family:ui-monospace,Menlo,monospace; font-size:10px; color:#6e7681;
  margin-top:2px; }
.ovr { margin-top:6px; font-size:11.5px; color:var(--crit); }
.ovr .s { color:var(--dim); }
button.ap { background:rgba(63,185,80,.14); color:var(--good);
  border:1px solid rgba(63,185,80,.4); border-radius:6px; padding:5px 12px;
  font:12px inherit; cursor:pointer; }
button.ap:hover { background:rgba(63,185,80,.24); }
button.ap:disabled { opacity:.45; cursor:default; }
.res.err { color:var(--crit); } .res.ok { color:var(--good); }
footer { padding:0 32px 40px; color:var(--dim); font-size:12px; }
mark { background:rgba(210,153,34,.32); color:inherit; border-radius:2px; padding:0 1px; }

button.doc { background:none; border:none; padding:0; cursor:pointer; color:var(--acc);
  font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace; text-decoration:underline;
  text-decoration-color:rgba(88,166,255,.35); text-underline-offset:3px; }
button.doc:hover { text-decoration-color:var(--acc); }

/* ---------------------------------------------------------------- overlays */
.ovl { position:fixed; inset:0; background:rgba(4,6,9,.82); display:none;
  place-items:center; padding:36px; z-index:50; }
.ovl.on { display:grid; }
.sheet { background:var(--panel); border:1px solid var(--line); border-radius:12px;
  width:min(1180px,100%); height:min(860px,100%); display:grid;
  grid-template-columns:1fr 340px; overflow:hidden; }
.sheet .page-wrap { padding:22px; background:#0b0f14; display:grid; place-items:center;
  min-height:0; }
/* A4 proportions, sized to the height available. Sizing to width instead pushes the
   bottom of the page out of the panel, which hides exactly the spans a reviewer most
   needs to see -- the payment details and the note at the foot of the invoice. */
.page { position:relative; height:100%; aspect-ratio:1/1.414; width:auto;
  max-width:100%; background:#f7f7f4; border-radius:3px;
  box-shadow:0 10px 40px rgba(0,0,0,.5); }
.sp { position:absolute; font:11px/1.25 ui-monospace,Menlo,monospace; color:#1a1d21;
  display:flex; align-items:center; padding:0 3px; overflow:hidden;
  border:1px solid rgba(20,24,30,.16); border-radius:2px;
  background:rgba(255,255,255,.4); }
.sp.flag { background:rgba(248,81,73,.2); border-color:rgba(200,30,25,.75);
  box-shadow:0 0 0 2px rgba(248,81,73,.28); color:#7a1410; font-weight:600; }
.sp.note { font-size:9.5px; line-height:1.2; align-items:flex-start; padding-top:2px; }
.side { border-left:1px solid var(--line); padding:24px; overflow:auto; }
.side h2 { margin:0 0 3px; font-size:15px; }
.side .hash { font:10.5px ui-monospace,Menlo,monospace; color:var(--dim);
  word-break:break-all; margin-bottom:14px; }
.side h3 { margin:18px 0 8px; font-size:10.5px; letter-spacing:.07em;
  text-transform:uppercase; color:var(--dim); font-weight:600; }
.fi { border-left:2px solid var(--crit); padding:2px 0 2px 10px; margin-bottom:12px; }
.fi .c { font:11px ui-monospace,Menlo,monospace; color:var(--crit); }
.fi .d { font-size:12px; color:var(--dim); margin-top:2px; }
.fi .v { font:12px ui-monospace,Menlo,monospace; margin-top:5px; }
.fi .sid { font:10px ui-monospace,Menlo,monospace; color:#6e7681; margin-top:2px; }
.intact { display:inline-block; font-size:10px; font-weight:700; letter-spacing:.06em;
  text-transform:uppercase; padding:2px 7px; border-radius:4px; margin-bottom:12px; }
.intact.y { background:rgba(63,185,80,.15); color:var(--good); }
.intact.n { background:rgba(248,81,73,.16); color:var(--crit); }
.ovx { position:absolute; top:20px; right:26px; background:none; border:none;
  color:var(--dim); font-size:26px; line-height:1; cursor:pointer; z-index:2; }
.ovx:hover { color:var(--tx); }

/* ------------------------------------------------------------- audit view */
.audit { background:var(--panel); border:1px solid var(--line); border-radius:12px;
  width:min(880px,100%); max-height:100%; overflow:auto; padding:30px 34px 34px; }
.audit h2 { margin:0 0 4px; font-size:17px; letter-spacing:-.01em; }
.audit .sub { color:var(--dim); font-size:12.5px; margin-bottom:6px; }
.audit .note { color:var(--dim); font-size:11.5px; margin-bottom:22px;
  padding-bottom:16px; border-bottom:1px solid var(--line); }
.stage { display:grid; grid-template-columns:26px 1fr; gap:14px; }
.rail { display:flex; flex-direction:column; align-items:center; }
.dot { width:11px; height:11px; border-radius:50%; background:#30363d; margin-top:4px;
  flex:none; border:2px solid var(--panel); box-shadow:0 0 0 1px #30363d; }
.dot.good { background:var(--good); box-shadow:0 0 0 1px var(--good); }
.dot.crit { background:var(--crit); box-shadow:0 0 0 1px var(--crit); }
.dot.acc { background:var(--acc); box-shadow:0 0 0 1px var(--acc); }
.dot.open { background:var(--panel); box-shadow:0 0 0 1px var(--dim); }
.line { width:1px; flex:1; background:var(--line); margin:3px 0; min-height:14px; }
.body { padding-bottom:20px; min-width:0; }
.stage:last-child .body { padding-bottom:0; }
.stage:last-child .line { display:none; }
.st { font:10.5px ui-monospace,Menlo,monospace; letter-spacing:.09em;
  text-transform:uppercase; color:var(--dim); }
.sh { font-size:13.5px; margin-top:3px; }
.sh b { font-weight:600; }
.sh .mono { font-family:ui-monospace,Menlo,monospace; font-size:12.5px; }
.kv { margin-top:8px; font:11.5px ui-monospace,Menlo,monospace; color:var(--dim);
  word-break:break-all; }
.kv span { color:var(--tx); }
.quote { margin-top:8px; padding:9px 12px; background:#0b0f14; border-radius:7px;
  border-left:2px solid var(--line); font-size:12.5px; color:#c9d1d9; }
.quote.crit { border-left-color:var(--crit); }
.refused { color:var(--crit); font-weight:600; }
.pill { display:inline-block; font:10px ui-monospace,Menlo,monospace; padding:1px 7px;
  border-radius:20px; background:#21262d; color:var(--dim); margin-left:6px; }
.pill.crit { background:rgba(248,81,73,.16); color:var(--crit); }
.pill.good { background:rgba(63,185,80,.14); color:var(--good); }
.legend { margin-top:11px; display:flex; flex-wrap:wrap; gap:5px 18px;
  font-size:11px; color:var(--dim); line-height:1.7; }
.legend span { display:flex; align-items:baseline; gap:6px; }
.legend i.dot { display:inline-block; margin-top:0; position:relative; top:1px; }
.legend b { color:var(--crit); font-weight:600; }
.audit .foot { margin-top:24px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--dim); font-size:11.5px; }

/* -------------------------------------------------------------- key help */
.help { background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:26px 30px; width:min(430px,100%); }
.help h2 { margin:0 0 16px; font-size:15px; }
.help dl { margin:0; display:grid; grid-template-columns:auto 1fr; gap:9px 16px;
  align-items:baseline; }
.help dt { text-align:right; }
.help dd { margin:0; color:var(--dim); font-size:12.5px; }
.help kbd { font:11px ui-monospace,Menlo,monospace; background:#21262d;
  border:1px solid var(--line); border-bottom-width:2px; border-radius:4px;
  padding:2px 6px; color:#c9d1d9; }
"""

# --------------------------------------------------------------------------- script
# Placeholders are substituted rather than f-string-formatted: this block is mostly
# braces, and escaping every one of them is how the page used to break.
SCRIPT = r"""
var TENANT = __TENANT__;
var ROWS   = __ROWS__;      // one entry per table row, in table order
var BYID   = {};
ROWS.forEach(function (r) { BYID[r.doc_id] = r; });

function esc(t) {
  var d = document.createElement("div"); d.textContent = t == null ? "" : t;
  return d.innerHTML;
}

/* ==================================================================== filtering
   Every filter runs against data embedded in the page, so the queue stays fully
   navigable under `make demo` with no server running. */

var tbody   = document.getElementById("tbody");
var trs     = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
var qEl     = document.getElementById("q");
var shownEl = document.getElementById("shown");
var emptyEl = document.getElementById("empty");

var view    = "all";   // one of: all cleared escalated override injected approved
var codes   = {};      // set of finding codes; empty means "any"
var visible = [];      // trs currently shown, in order -- what j/k walks
var sel     = -1;

function matches(r) {
  if (view === "cleared"   && r.decision !== "resolve")  return false;
  if (view === "escalated" && r.decision !== "escalate") return false;
  if (view === "override"  && !r.overridden)             return false;
  if (view === "injected"  && !r.injected)               return false;
  if (view === "approved"  && !r.approved_by)            return false;

  var want = Object.keys(codes);
  if (want.length) {
    var hit = false;
    for (var i = 0; i < want.length; i++) {
      if (r.codes.indexOf(want[i]) !== -1) { hit = true; break; }
    }
    if (!hit) return false;
  }

  var q = qEl.value.trim().toLowerCase();
  if (q && r.search.indexOf(q) === -1) return false;
  return true;
}

function apply(keepSel) {
  var prev = sel >= 0 && visible[sel] ? visible[sel].dataset.doc : null;
  visible = [];
  trs.forEach(function (tr) {
    var ok = matches(BYID[tr.dataset.doc]);
    tr.classList.toggle("gone", !ok);
    if (ok) visible.push(tr);
  });

  shownEl.innerHTML = "<b>" + visible.length + "</b> of " + trs.length;
  emptyEl.classList.toggle("on", visible.length === 0);

  sel = -1;
  if (keepSel && prev) {
    for (var i = 0; i < visible.length; i++) {
      if (visible[i].dataset.doc === prev) { sel = i; break; }
    }
  }
  paint();
  highlight();
}

function paint() {
  trs.forEach(function (tr) { tr.classList.remove("sel"); });
  if (sel >= 0 && visible[sel]) {
    visible[sel].classList.add("sel");
    visible[sel].scrollIntoView({ block: "nearest" });
  }
}

/* Search marks its hits. Only text nodes are touched, so the markup a cell needs --
   badges, provenance, buttons -- survives being highlighted. */
function highlight() {
  var q = qEl.value.trim();
  visible.concat([]).forEach(function (tr) {
    tr.querySelectorAll("mark").forEach(function (m) {
      var p = m.parentNode; p.replaceChild(document.createTextNode(m.textContent), m);
      p.normalize();
    });
  });
  if (q.length < 2) return;
  var needle = q.toLowerCase();
  visible.forEach(function (tr) {
    var walk = document.createTreeWalker(tr, NodeFilter.SHOW_TEXT, null);
    var hits = [], n;
    while ((n = walk.nextNode())) {
      if (n.nodeValue.toLowerCase().indexOf(needle) !== -1) hits.push(n);
    }
    hits.forEach(function (node) {
      var txt = node.nodeValue, low = txt.toLowerCase(), frag = document.createDocumentFragment();
      var at = 0, i;
      while ((i = low.indexOf(needle, at)) !== -1) {
        frag.appendChild(document.createTextNode(txt.slice(at, i)));
        var m = document.createElement("mark");
        m.textContent = txt.slice(i, i + needle.length);
        frag.appendChild(m);
        at = i + needle.length;
      }
      frag.appendChild(document.createTextNode(txt.slice(at)));
      node.parentNode.replaceChild(frag, node);
    });
  });
}

qEl.addEventListener("input", function () { apply(true); });

document.querySelectorAll("#views .chip").forEach(function (c) {
  c.addEventListener("click", function () {
    view = c.dataset.view;
    document.querySelectorAll("#views .chip").forEach(function (o) {
      o.classList.toggle("on", o === c);
    });
    apply(false);
  });
});

document.querySelectorAll("#codes .chip").forEach(function (c) {
  c.addEventListener("click", function () {
    var code = c.dataset.code;
    if (!code) {                       // the "clear" chip
      codes = {};
      document.querySelectorAll("#codes .chip").forEach(function (o) {
        o.classList.remove("on");
      });
    } else {
      if (codes[code]) { delete codes[code]; } else { codes[code] = 1; }
      c.classList.toggle("on", !!codes[code]);
    }
    apply(true);
  });
});

/* ==================================================================== overlays */

var ov = document.getElementById("ov");
var au = document.getElementById("au");
var hp = document.getElementById("hp");
var pageEl = document.getElementById("page");
var sideEl = document.getElementById("side");
var auEl   = document.getElementById("aubody");

function anyOpen() {
  return ov.classList.contains("on") || au.classList.contains("on") ||
         hp.classList.contains("on");
}
function closeAll() {
  ov.classList.remove("on"); au.classList.remove("on"); hp.classList.remove("on");
}
[ov, au, hp].forEach(function (o) {
  o.addEventListener("click", function (e) { if (e.target === o) closeAll(); });
});
document.querySelectorAll(".ovx").forEach(function (b) {
  b.addEventListener("click", closeAll);
});

/* -------------------------------------------------------------- document viewer
   Spans are drawn at their own bbox, so a reviewer sees where on the page a flagged
   value physically sits -- the same coordinates the span id encodes. Needs the
   server, because the spans come from the annotation file. */
function openDoc(docId) {
  closeAll();
  pageEl.innerHTML = "";
  sideEl.innerHTML = '<h2>' + esc(docId) + '</h2><div class="hash">loading…</div>';
  ov.classList.add("on");

  fetch("/document?doc=" + encodeURIComponent(docId) + "&tenant=" + encodeURIComponent(TENANT))
    .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
    .then(function (p) {
      var status = p[0], d = p[1];
      if (status !== 200) {
        sideEl.innerHTML = '<h2>' + esc(docId) + '</h2><div class="hash">' +
          esc(d.error || ("HTTP " + status)) + "</div>";
        return;
      }

      d.spans.forEach(function (sp) {
        var b = sp.bbox, el = document.createElement("div");
        el.className = "sp" + (sp.flagged ? " flag" : "") +
                       (sp.fieldtype === "other" ? " note" : "");
        el.style.left = (b[0] * 100) + "%";
        el.style.top = (b[1] * 100) + "%";
        el.style.width = ((b[2] - b[0]) * 100) + "%";
        el.style.height = ((b[3] - b[1]) * 100) + "%";
        el.title = sp.span_id + "  ·  " + (sp.fieldtype || "");
        el.textContent = sp.text;
        pageEl.appendChild(el);
      });

      var h = '<h2>' + esc(d.doc_id) + '</h2>';
      h += '<div class="intact ' + (d.intact ? "y" : "n") + '">' +
           (d.intact ? "hash matches" : "hash differs") + "</div>";
      h += '<div class="hash">sha256 ' + esc(d.doc_hash) + "</div>";
      h += "<h3>supplier</h3><div>" + esc(d.vendor || "unknown") + "</div>";
      h += "<h3>why it was flagged</h3>";
      if (!d.findings.length) h += '<div class="fi"><div class="d">no findings</div></div>';
      d.findings.forEach(function (f) {
        h += '<div class="fi"><div class="c">' + esc(f.code) + "</div>";
        h += '<div class="d">' + esc(f.detail || "") + "</div>";
        if (f.value) h += '<div class="v">' + esc(f.value) + "</div>";
        if (f.span_id) h += '<div class="sid">' + esc(f.span_id) + "</div>";
        h += "</div>";
      });
      h += "<h3>the whole document</h3>" +
           '<div style="font-size:12px;color:#8b949e">' + d.spans.length +
           " spans. Everything the reader was shown, and nothing else.</div>";
      sideEl.innerHTML = h;
    })
    .catch(function () {
      sideEl.innerHTML = '<h2>' + esc(docId) +
        '</h2><div class="hash">no server — run: make serve</div>';
    });
}

/* ------------------------------------------------------------------ audit view
   One document, replayed through the pipeline. Every line below is read off the
   stored record; where the store holds nothing for a stage, the stage says so
   rather than narrating what probably happened. Needs no server. */
function stage(dot, label, head, extra) {
  return '<div class="stage"><div class="rail"><div class="dot ' + dot +
         '"></div><div class="line"></div></div><div class="body">' +
         '<div class="st">' + label + '</div><div class="sh">' + head + '</div>' +
         (extra || "") + "</div></div>";
}

function openAudit(docId) {
  var r = BYID[docId];
  if (!r) return;
  closeAll();

  var h = "";

  // 1. the document
  h += stage("acc", "1 &middot; document",
    "<b>" + esc(r.doc_id) + "</b> from <b>" + esc(r.vendor) + "</b>",
    '<div class="kv">sha256 <span>' + esc(r.doc_hash || "not recorded") + "</span>" +
    "<br>prior invoices from this supplier <span>" + r.peers + "</span>" +
    (r.injected ? '<br><span class="refused">this document carries a planted ' +
                  'injection payload</span>' : "") + "</div>");

  // 2. reader + resolver, evidenced by what the values carry
  var ev = r.evidence || {}, fields = Object.keys(ev);
  var refs = fields.filter(function (f) { return ev[f].span_id; }).length;
  var tainted = fields.filter(function (f) { return ev[f].tainted; }).length;
  var kv = "";
  fields.forEach(function (f) {
    kv += "<br>" + esc(f) + " <span>" + esc(ev[f].value) + "</span> &larr; " +
          esc(ev[f].span_id || "no span");
  });
  h += stage(refs === fields.length && fields.length ? "good" : "",
    "2 &middot; reader &rarr; resolver",
    fields.length
      ? "<b>" + refs + " of " + fields.length + "</b> value" +
        (fields.length === 1 ? "" : "s") + " resolved from a span reference" +
        '<span class="pill' + (tainted === fields.length ? " crit" : "") + '">' +
        tainted + " tainted</span>"
      : "no values carried into the record",
    '<div class="kv">every value below is a lookup into the immutable document; ' +
    "the model returned the reference, never the text" + kv + "</div>");

  // 3. rules
  var fx = "";
  (r.findings || []).forEach(function (f) {
    fx += '<div class="quote"><b class="mono">' + esc(f.code) + "</b> &middot; " +
          esc(f.field) + "<br>" + esc(f.detail || "") + "</div>";
  });
  h += stage("crit", "3 &middot; rules baseline",
    "<b>" + (r.findings || []).length + "</b> finding" +
    ((r.findings || []).length === 1 ? "" : "s") + " &mdash; no model involved", fx);

  // 4. agent
  h += stage(r.agent_decision === "resolve" ? "good" : "",
    "4 &middot; exception agent",
    "voted <b>" + esc(r.agent_decision) + "</b>" +
    '<span class="pill">' + esc(r.model || "model not recorded") + "</span>",
    r.reason ? '<div class="quote">' + esc(r.reason) + "</div>"
             : '<div class="kv">no reasoning recorded</div>');

  // 5. gate
  if (r.overridden) {
    h += stage("crit", "5 &middot; policy gate",
      '<span class="refused">REFUSED the agent’s vote</span> &mdash; deterministic, no LLM',
      '<div class="quote crit">' + esc(r.override_reason || "policy") + "</div>" +
      '<div class="kv">agent said <span>' + esc(r.agent_decision) +
      "</span>, gate returned <span>" + esc(r.decision) + "</span></div>");
  } else {
    h += stage(r.decision === "resolve" ? "good" : "", "5 &middot; policy gate",
      "let the vote stand &mdash; <b>" + esc(r.decision) + "</b>",
      '<div class="kv">no privileged field, no document-claimed authority, ' +
      "no cross-tenant lookup</div>");
  }

  // 6. human
  if (r.approved_by) {
    h += stage("good", "6 &middot; human approval",
      "approved by <b class=\"mono\">" + esc(r.approved_by) + "</b>",
      '<div class="kv">at <span>' + esc(r.approved_at || "time not recorded") +
      "</span><br>identity taken from the session, not from the page</div>");
  } else if (r.decision === "escalate") {
    h += stage("open", "6 &middot; human approval", "awaiting a person",
      '<div class="kv">the agent can propose. It can never approve.</div>');
  } else {
    h += stage("good", "6 &middot; human approval", "not required",
      '<div class="kv">cleared before it reached a person &mdash; ' +
      "one human touch removed</div>");
  }

  auEl.innerHTML =
    "<h2>Audit trail &middot; " + esc(r.doc_id) + "</h2>" +
    '<div class="sub">Chain of custody, ingest to approval.</div>' +
    '<div class="note">Read from the stored record only. A stage the store holds ' +
    "nothing for says so rather than being narrated." +
    '<div class="legend">' +
    '<span><i class="dot acc"></i>where the document entered</span>' +
    '<span><i class="dot good"></i>the stage let the document through</span>' +
    '<span><i class="dot crit"></i>the stage objected &mdash; a rule fired, ' +
    "or the gate refused</span>" +
    '<span><i class="dot open"></i>not done yet</span>' +
    "</div>" +
    '<div class="legend"><span><b>tainted</b> means the value was lifted off a ' +
    "document nobody trusts. It is a label that travels with the value, not a " +
    "judgement that the value is wrong.</span></div></div>" + h +
    '<div class="foot">Ground truth for this document: <b>' + esc(r.correct) +
    "</b> &middot; final decision: <b>" + esc(r.decision) + "</b>" +
    (r.correct !== "?" && r.correct !== r.decision
      ? ' &middot; <span class="refused">these disagree</span>' : "") + "</div>";
  au.classList.add("on");
}

/* ==================================================================== approving */

function approveRow(docId) {
  var b = document.querySelector('button.ap[data-doc="' + docId + '"]');
  if (!b || b.disabled) return;
  var out = document.getElementById("res-" + docId);
  b.disabled = true; out.className = "s res"; out.textContent = "approving…";
  fetch("/approve", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, tenant: TENANT })
  }).then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
    .then(function (p) {
      var status = p[0], j = p[1];
      if (status === 200) {
        out.className = "s res ok";
        out.textContent = "APPROVED by " + j.approved_by;
      } else {
        out.className = "s res err";
        out.textContent = "REFUSED — " + (j.error || status);
        b.disabled = false;
      }
    })
    .catch(function () {
      out.className = "s res err";
      out.textContent = "no server — run: make serve";
      b.disabled = false;
    });
}

/* ==================================================================== bindings */

document.querySelectorAll("button.doc").forEach(function (b) {
  b.addEventListener("click", function () { openDoc(b.dataset.doc); });
});
document.querySelectorAll("button.ap").forEach(function (b) {
  b.addEventListener("click", function () { approveRow(b.dataset.doc); });
});
document.querySelectorAll("[data-audit]").forEach(function (b) {
  b.addEventListener("click", function () { openAudit(b.dataset.audit); });
});

function isTyping(e) {
  var t = e.target.tagName;
  return t === "INPUT" || t === "TEXTAREA" || t === "SELECT";
}

document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    if (anyOpen()) { closeAll(); return; }
    if (document.activeElement === qEl) {
      if (qEl.value) { qEl.value = ""; apply(true); } else { qEl.blur(); }
    }
    return;
  }
  if (e.key === "/" && !isTyping(e)) { e.preventDefault(); qEl.focus(); qEl.select(); return; }
  if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (anyOpen()) return;

  var k = e.key;
  if (k === "j" || k === "ArrowDown") {
    e.preventDefault();
    if (visible.length) { sel = Math.min(sel + 1, visible.length - 1); paint(); }
  } else if (k === "k" || k === "ArrowUp") {
    e.preventDefault();
    if (visible.length) { sel = sel <= 0 ? 0 : sel - 1; paint(); }
  } else if (k === "g") {
    if (visible.length) { sel = 0; paint(); }
  } else if (k === "G") {
    if (visible.length) { sel = visible.length - 1; paint(); }
  } else if (k === "Enter" || k === "o") {
    if (sel >= 0 && visible[sel]) { e.preventDefault(); openDoc(visible[sel].dataset.doc); }
  } else if (k === "u") {
    if (sel >= 0 && visible[sel]) openAudit(visible[sel].dataset.doc);
  } else if (k === "a") {
    if (sel >= 0 && visible[sel]) approveRow(visible[sel].dataset.doc);
  } else if (k === "?") {
    hp.classList.add("on");
  }
});

apply(false);
"""


def render(rows, total, resolved, escalated, overrides, wrong, prec,
           source="", known=(), tenant="", user="", role="") -> str:
    def card(label, value, sub="", tone=""):
        return (f'<div class="card {tone}"><div class="v">{value}</div>'
                f'<div class="l">{label}</div><div class="s">{sub}</div></div>')

    stats = "".join([
        card("flagged by rules", total, "every one would reach a human"),
        card("cleared by agent", len(resolved), "no human needed", "good"),
        card("sent to a human", len(escalated), "with evidence attached"),
        card("resolve precision", f"{prec*100:.1f}%",
             f"{len(wrong)} wrong of {len(resolved)}", "good" if not wrong else "warn"),
        card("gate overrides", len(overrides), "agent voted resolve, code refused", "crit"),
    ])

    # ------------------------------------------------------------------ controls
    n_injected = sum(1 for r in rows if r["injected"])
    n_approved = sum(1 for r in rows if r["approved_by"])
    views = [
        ("all", "all", total, ""),
        ("cleared", "cleared", len(resolved), "good"),
        ("escalated", "escalated", len(escalated), ""),
        ("override", "gate overrode", len(overrides), "crit"),
        ("injected", "injected", n_injected, "warn"),
        ("approved", "approved", n_approved, "good"),
    ]
    view_chips = "".join(
        f'<button class="chip {tone}{" on" if key == "all" else ""}'
        f'{" zero" if not n else ""}" data-view="{key}">{html.escape(label)}'
        f'<span class="n">{n}</span></button>'
        for key, label, n, tone in views)

    counts: dict[str, int] = {}
    for r in rows:
        for c in set(r["codes"]):
            counts[c] = counts.get(c, 0) + 1
    ordered = [c for c in CODE_ORDER if c in counts]
    ordered += sorted(c for c in counts if c not in CODE_ORDER)
    code_chips = "".join(
        f'<button class="chip" data-code="{html.escape(c)}">{html.escape(c)}'
        f'<span class="n">{counts[c]}</span></button>' for c in ordered)
    code_chips += '<button class="chip clear" data-code="">clear</button>'

    controls = f"""<div class="controls">
<div class="crow">
  <div class="search"><span class="mag">&#9906;</span>
    <input id="q" type="search" autocomplete="off" spellcheck="false"
           placeholder="search document, supplier, code, reason, account…"></div>
  <div class="shown" id="shown"><b>{total}</b> of {total}</div>
  <div class="hint"><kbd>/</kbd> search &nbsp; <kbd>j</kbd><kbd>k</kbd> move &nbsp;
    <kbd>enter</kbd> open &nbsp; <kbd>u</kbd> audit &nbsp; <kbd>?</kbd> keys</div>
</div>
<div class="crow chips" id="views"><span class="lbl">show</span>{view_chips}</div>
<div class="crow chips" id="codes"><span class="lbl">finding</span>{code_chips}</div>
</div>"""

    # --------------------------------------------------------------------- rows
    trs = []
    payload = []
    for r in rows:
        out = outcome_of(r)
        if out == "approved":
            badge = '<span class="b good" data-audit="{d}">approved</span>'
        elif out == "override":
            badge = '<span class="b crit" data-audit="{d}">GATE OVERRODE</span>'
        elif out == "cleared":
            badge = '<span class="b good" data-audit="{d}">cleared</span>'
        else:
            badge = '<span class="b" data-audit="{d}">escalated</span>'
        badge = badge.format(d=html.escape(r["doc_id"]))
        inj = '<span class="b warn">injected</span>' if r["injected"] else ""

        codes = " ".join(f'<span class="code">{html.escape(c)}</span>' for c in r["codes"])
        detail = "<br>".join(
            f'<span class="d">{html.escape(f["code"])}</span> {html.escape(f["detail"])}'
            for f in r["findings"]) or "&mdash;"

        # Provenance: the whole point is that this is visible before anyone approves.
        prov = ""
        for field, ev in (r["evidence"] or {}).items():
            tag = ('<span class="t">TAINTED</span>' if ev.get("tainted")
                   else '<span class="t ok">trusted</span>')
            prov += (f'<div class="prov">{tag}'
                     f'<span class="pv">{html.escape(str(ev.get("value", "")))}</span>'
                     f'<div class="ps">{html.escape(field)} '
                     f'&middot; {html.escape(str(ev.get("span_id", "?")))} '
                     f'&middot; doc {html.escape(str(ev.get("doc_hash", "?")))}</div></div>')
        prov = prov or '<span class="s">&mdash;</span>'

        why = ""
        if r["overridden"]:
            why = (f'<div class="ovr">gate refused: '
                   f'{html.escape(r["override_reason"] or "policy")}'
                   f'<div class="s">agent voted <b>{html.escape(r["agent_decision"])}</b>'
                   f'</div></div>')

        act = ""
        if r["decision"] == "escalate":
            if r["approved_by"]:
                act = f'<div class="s">approved by <b>{html.escape(r["approved_by"])}</b></div>'
            elif role == "approver":
                act = (f'<button class="ap" data-doc="{html.escape(r["doc_id"])}">approve'
                       f'</button>'
                       f'<div class="s res" id="res-{html.escape(r["doc_id"])}"></div>')
            else:
                act = '<div class="s">view only</div>'

        trs.append(f"""<tr data-doc="{html.escape(r['doc_id'])}">
<td><button class="doc" data-doc="{html.escape(r['doc_id'])}">{html.escape(r['doc_id'])}</button>
    <div class="s"><a href="#" data-audit="{html.escape(r['doc_id'])}"
       style="color:#6e7681;text-decoration:none">audit &rarr;</a></div></td>
<td>{html.escape(r['vendor'][:34])}<div class="s">{r['peers']} prior invoices</div></td>
<td>{codes}<div class="s">{detail}</div></td>
<td>{prov}</td>
<td>{badge} {inj}{why}</td>
<td class="reason">{html.escape(clip(r["reason"], 150))}</td>
<td>{act}</td></tr>""")

        # Everything the client needs to filter, search and replay one document.
        # `search` is precomputed so keystroke filtering never rebuilds a haystack.
        hay = " ".join(str(x) for x in [
            r["doc_id"], r["vendor"], " ".join(r["codes"]), r["reason"],
            r["override_reason"] or "", r["agent_decision"], r["decision"],
            r["approved_by"] or "",
            " ".join(f["detail"] for f in r["findings"]),
            " ".join(f'{k} {v.get("value", "")} {v.get("span_id", "")}'
                     for k, v in (r["evidence"] or {}).items()),
        ]).lower()
        payload.append({
            "doc_id": r["doc_id"], "vendor": r["vendor"], "peers": r["peers"],
            "codes": r["codes"], "findings": r["findings"], "evidence": r["evidence"],
            "decision": r["decision"], "agent_decision": r["agent_decision"],
            "overridden": r["overridden"], "override_reason": r["override_reason"],
            "reason": r["reason"], "correct": r["correct"], "injected": r["injected"],
            "approved_by": r["approved_by"], "approved_at": r.get("approved_at"),
            "model": r.get("model"), "doc_hash": r.get("doc_hash", ""),
            "search": hay,
        })

    if len(known) > 1:
        opts = "".join(
            f'<option value="{t}"{" selected" if t == tenant else ""}>{t}</option>'
            for t in known)
        tenant_picker = (f'&nbsp;&nbsp;client <select id="tsel" '
                         f'onchange="location.search=\'?tenant=\'+this.value">'
                         f'{opts}</select>')
    else:
        tenant_picker = ""

    script = (SCRIPT
              .replace("__TENANT__", json.dumps(tenant))
              .replace("__ROWS__", json.dumps(payload)))

    return f"""<!doctype html><meta charset="utf-8">
<title>PRAETOR review queue</title>
<style>{CSS}</style>
<header>
<h1>PRAETOR &mdash; invoice review queue</h1>
<p>Rules flag; the agent adjudicates; the policy gate has the last word. Every value
shown carries the span and document hash it came from, so approving is a
declassification with the evidence attached &mdash; not a rubber stamp.
Every figure is read from a results file, not written by hand.</p>
<div class="who">signed in as <b class="me">{user or "not signed in"}</b>
<span class="role">{role or "no role"}</span>{tenant_picker}
&nbsp;<a class="out" href="/logout">sign out</a>
&nbsp;<span class="s">identity comes from the session, not from this page</span></div>
</header>
<div class="stats">{stats}</div>
{controls}
<table>
<thead><tr><th>document</th><th>supplier</th><th>why it was flagged</th>
<th>provenance</th><th>outcome</th><th>agent's reasoning</th><th>action</th></tr></thead>
<tbody id="tbody">
{''.join(trs)}
</tbody></table>
<div id="empty">Nothing matches that filter. <kbd>esc</kbd> to clear the search,
or pick <b>all</b> above.</div>
<footer>Generated {datetime.now():%d %b %Y %H:%M} from {source} &middot;
constructed corpus, synthetic purchase orders &mdash; labelled as such.<br>
Approvals are live only under <code>python3 dashboard/serve.py</code>; opening this file
directly shows the queue read-only. Filtering, search and the audit view need no server.
</footer>

<div class="ovl" id="ov"><button class="ovx" aria-label="close">&times;</button>
<div class="sheet"><div class="page-wrap"><div class="page" id="page"></div></div>
<div class="side" id="side"></div></div></div>

<div class="ovl" id="au"><button class="ovx" aria-label="close">&times;</button>
<div class="audit" id="aubody"></div></div>

<div class="ovl" id="hp"><div class="help">
<h2>Keyboard</h2>
<dl>
<dt><kbd>/</kbd></dt><dd>focus search</dd>
<dt><kbd>j</kbd> <kbd>k</kbd></dt><dd>move down / up the queue</dd>
<dt><kbd>g</kbd> <kbd>G</kbd></dt><dd>first row / last row</dd>
<dt><kbd>enter</kbd> <kbd>o</kbd></dt><dd>open the document as the reader saw it</dd>
<dt><kbd>u</kbd></dt><dd>audit trail for the selected row</dd>
<dt><kbd>a</kbd></dt><dd>approve the selected row</dd>
<dt><kbd>esc</kbd></dt><dd>close, or clear the search</dd>
<dt><kbd>?</kbd></dt><dd>this list</dd>
</dl></div></div>

<script>{script}</script>
"""


if __name__ == "__main__":
    main()
