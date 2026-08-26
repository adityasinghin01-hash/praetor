"""Build the review dashboard from real result files.

This is what appears in the demo video: the queue a human actually works. It reads the
adjudication results, the rules findings and the ground truth, and renders a single
self-contained HTML file with no external dependencies.

Two things on this page are not decoration:

  * Every flagged value carries its provenance — TAINTED, the span it came from, the
    hash of the document it came from. A person approving a payment can see that the
    figure they are approving was lifted off an untrusted document, and exactly where.
  * The approve control posts to dashboard/serve.py, which calls the real
    praetor.gate.approve(). Approving as an agent returns the real PermissionError.

Every number comes from a results file. Nothing is hardcoded.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praetor import store  # noqa: E402


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
        rows.append({
            "doc_id": doc_id,
            "vendor": e.get("vendor_key", "?"),
            "peers": e.get("n_peer_invoices", 0),
            "codes": a.get("codes", []),
            "findings": e.get("findings", []),
            "evidence": e.get("evidence", {}),
            "decision": a["decision"],
            "agent_decision": a["agent_decision"],
            "overridden": a["overridden"],
            "override_reason": a.get("override_reason"),
            "reason": a.get("reason", ""),
            "correct": t.get("correct_action", "?"),
            "injected": bool(t.get("injected")),
            "approved_by": None,
        })
    return rows, []


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

    trs = []
    for r in rows:
        if r["approved_by"]:
            badge = '<span class="b good">approved</span>'
        elif r["overridden"]:
            badge = '<span class="b crit">GATE OVERRODE</span>'
        elif r["decision"] == "resolve":
            badge = '<span class="b good">cleared</span>'
        else:
            badge = '<span class="b">escalated</span>'
        inj = '<span class="b warn">injected</span>' if r["injected"] else ""

        codes = " ".join(f'<span class="code">{c}</span>' for c in r["codes"])
        detail = "<br>".join(f'<span class="d">{f["code"]}</span> {f["detail"]}'
                             for f in r["findings"]) or "&mdash;"

        # Provenance: the whole point is that this is visible before anyone approves.
        prov = ""
        for field, ev in (r["evidence"] or {}).items():
            tag = ('<span class="t">TAINTED</span>' if ev.get("tainted")
                   else '<span class="t ok">trusted</span>')
            prov += (f'<div class="prov">{tag}<span class="pv">{ev.get("value", "")}</span>'
                     f'<div class="ps">{field} &middot; {ev.get("span_id", "?")} '
                     f'&middot; doc {ev.get("doc_hash", "?")}</div></div>')
        prov = prov or '<span class="s">&mdash;</span>'

        why = ""
        if r["overridden"]:
            why = (f'<div class="ovr">gate refused: {r["override_reason"] or "policy"}'
                   f'<div class="s">agent voted <b>{r["agent_decision"]}</b></div></div>')

        act = ""
        if r["decision"] == "escalate":
            if r["approved_by"]:
                act = f'<div class="s">approved by <b>{r["approved_by"]}</b></div>'
            elif role == "approver":
                act = (f'<button class="ap" data-doc="{r["doc_id"]}">approve</button>'
                       f'<div class="s res" id="res-{r["doc_id"]}"></div>')
            else:
                act = '<div class="s">view only</div>' 

        trs.append(f"""<tr>
<td><button class="doc" data-doc="{r['doc_id']}">{r['doc_id']}</button></td>
<td>{r['vendor'][:34]}<div class="s">{r['peers']} prior invoices</div></td>
<td>{codes}<div class="s">{detail}</div></td>
<td>{prov}</td>
<td>{badge} {inj}{why}</td>
<td class="reason">{r['reason'][:150]}</td>
<td>{act}</td></tr>""")

    if len(known) > 1:
        opts = "".join(
            f'<option value="{t}"{" selected" if t == tenant else ""}>{t}</option>'
            for t in known)
        tenant_picker = (f'&nbsp;&nbsp;client <select id="tsel" '
                         f'onchange="location.search=\'?tenant=\'+this.value">'
                         f'{opts}</select>')
    else:
        tenant_picker = ""
    tenant_json = json.dumps(tenant)
    user_html = user or "not signed in"
    role_html = role or "no role"

    return f"""<!doctype html><meta charset="utf-8">
<title>PRAETOR review queue</title>
<style>
:root {{ --bg:#0e1116; --panel:#161b22; --line:#232a34; --tx:#e6edf3; --dim:#8b949e;
        --good:#3fb950; --warn:#d29922; --crit:#f85149; --acc:#58a6ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--tx);
  font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
header {{ padding:26px 32px 18px; border-bottom:1px solid var(--line); }}
h1 {{ margin:0; font-size:19px; letter-spacing:-.01em; }}
header p {{ margin:6px 0 0; color:var(--dim); font-size:13px; max-width:900px; }}
.who {{ margin-top:12px; font-size:12.5px; color:var(--dim); }}
.who select {{ background:#0b0f14; border:1px solid var(--line); color:var(--tx);
  border-radius:6px; padding:5px 9px; font:12.5px ui-monospace,Menlo,monospace;
  margin-left:6px; }}
.who .me {{ font-family:ui-monospace,Menlo,monospace; color:var(--tx); }}
.who .role {{ margin-left:7px; padding:2px 8px; border-radius:20px; font-size:11px;
  background:rgba(88,166,255,.14); color:var(--acc); }}
.who .out {{ color:var(--dim); }}
.stats {{ display:flex; gap:14px; padding:22px 32px; flex-wrap:wrap; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; min-width:158px; flex:1; }}
.card .v {{ font-size:27px; font-weight:600; letter-spacing:-.02em; }}
.card .l {{ color:var(--dim); font-size:12px; text-transform:uppercase;
  letter-spacing:.06em; margin-top:4px; }}
.card .s, td .s {{ color:var(--dim); font-size:11.5px; margin-top:3px; }}
.card.good .v {{ color:var(--good); }} .card.warn .v {{ color:var(--warn); }}
.card.crit .v {{ color:var(--crit); }}
table {{ width:calc(100% - 64px); margin:8px 32px 40px; border-collapse:collapse;
  background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
th {{ text-align:left; padding:11px 14px; font-size:11px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--dim); border-bottom:1px solid var(--line); }}
td {{ padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr:last-child td {{ border-bottom:none; }}
.mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; color:var(--acc); }}
.b {{ display:inline-block; padding:2px 8px; border-radius:20px; font-size:11px;
  background:#21262d; color:var(--dim); white-space:nowrap; }}
.b.good {{ background:rgba(63,185,80,.14); color:var(--good); }}
.b.warn {{ background:rgba(210,153,34,.14); color:var(--warn); }}
.b.crit {{ background:rgba(248,81,73,.16); color:var(--crit); font-weight:600; }}
.code {{ font-family:ui-monospace,monospace; font-size:11px; background:#21262d;
  padding:2px 6px; border-radius:4px; color:#c9d1d9; margin-right:4px; }}
.d {{ font-family:ui-monospace,monospace; font-size:10.5px; color:var(--dim); }}
.reason {{ color:var(--dim); font-size:12.5px; max-width:300px; }}
.prov {{ margin-bottom:7px; }}
.t {{ display:inline-block; font-size:9.5px; font-weight:700; letter-spacing:.07em;
  padding:1px 5px; border-radius:3px; background:rgba(248,81,73,.16); color:var(--crit);
  vertical-align:middle; }}
.t.ok {{ background:rgba(63,185,80,.14); color:var(--good); }}
.pv {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; margin-left:7px; }}
.ps {{ font-family:ui-monospace,Menlo,monospace; font-size:10px; color:#6e7681; margin-top:2px; }}
.ovr {{ margin-top:6px; font-size:11.5px; color:var(--crit); }}
.ovr .s {{ color:var(--dim); }}
button.ap {{ background:rgba(63,185,80,.14); color:var(--good); border:1px solid rgba(63,185,80,.4);
  border-radius:6px; padding:5px 12px; font:12px inherit; cursor:pointer; }}
button.ap:hover {{ background:rgba(63,185,80,.24); }}
button.ap:disabled {{ opacity:.45; cursor:default; }}
.res.err {{ color:var(--crit); }} .res.ok {{ color:var(--good); }}
footer {{ padding:0 32px 40px; color:var(--dim); font-size:12px; }}

button.doc {{ background:none; border:none; padding:0; cursor:pointer; color:var(--acc);
  font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace; text-decoration:underline;
  text-decoration-color:rgba(88,166,255,.35); text-underline-offset:3px; }}
button.doc:hover {{ text-decoration-color:var(--acc); }}

/* the document viewer */
#ov {{ position:fixed; inset:0; background:rgba(4,6,9,.82); display:none;
  place-items:center; padding:36px; z-index:50; }}
#ov.on {{ display:grid; }}
.sheet {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
  width:min(1180px,100%); height:min(860px,100%); display:grid;
  grid-template-columns:1fr 340px; overflow:hidden; }}
.sheet .page-wrap {{ padding:22px; background:#0b0f14; display:grid; place-items:center;
  min-height:0; }}
/* A4 proportions, sized to the height available. Sizing to width instead pushes the
   bottom of the page out of the panel, which hides exactly the spans a reviewer most
   needs to see -- the payment details and the note at the foot of the invoice. */
.page {{ position:relative; height:100%; aspect-ratio:1/1.414; width:auto;
  max-width:100%; background:#f7f7f4; border-radius:3px;
  box-shadow:0 10px 40px rgba(0,0,0,.5); }}
.sp {{ position:absolute; font:11px/1.25 ui-monospace,Menlo,monospace; color:#1a1d21;
  display:flex; align-items:center; padding:0 3px; overflow:hidden;
  border:1px solid rgba(20,24,30,.16); border-radius:2px; background:rgba(255,255,255,.4); }}
.sp.flag {{ background:rgba(248,81,73,.2); border-color:rgba(200,30,25,.75);
  box-shadow:0 0 0 2px rgba(248,81,73,.28); color:#7a1410; font-weight:600; }}
.sp.note {{ font-size:9.5px; line-height:1.2; align-items:flex-start; padding-top:2px; }}
.side {{ border-left:1px solid var(--line); padding:24px; overflow:auto; }}
.side h2 {{ margin:0 0 3px; font-size:15px; }}
.side .hash {{ font:10.5px ui-monospace,Menlo,monospace; color:var(--dim);
  word-break:break-all; margin-bottom:14px; }}
.side h3 {{ margin:18px 0 8px; font-size:10.5px; letter-spacing:.07em;
  text-transform:uppercase; color:var(--dim); font-weight:600; }}
.fi {{ border-left:2px solid var(--crit); padding:2px 0 2px 10px; margin-bottom:12px; }}
.fi .c {{ font:11px ui-monospace,Menlo,monospace; color:var(--crit); }}
.fi .d {{ font-size:12px; color:var(--dim); margin-top:2px; }}
.fi .v {{ font:12px ui-monospace,Menlo,monospace; margin-top:5px; }}
.fi .sid {{ font:10px ui-monospace,Menlo,monospace; color:#6e7681; margin-top:2px; }}
.intact {{ display:inline-block; font-size:10px; font-weight:700; letter-spacing:.06em;
  text-transform:uppercase; padding:2px 7px; border-radius:4px; margin-bottom:12px; }}
.intact.y {{ background:rgba(63,185,80,.15); color:var(--good); }}
.intact.n {{ background:rgba(248,81,73,.16); color:var(--crit); }}
#ovx {{ position:absolute; top:20px; right:26px; background:none; border:none;
  color:var(--dim); font-size:26px; line-height:1; cursor:pointer; }}
#ovx:hover {{ color:var(--tx); }}
</style>
<header>
<h1>PRAETOR &mdash; invoice review queue</h1>
<p>Rules flag; the agent adjudicates; the policy gate has the last word. Every value
shown carries the span and document hash it came from, so approving is a
declassification with the evidence attached &mdash; not a rubber stamp.
Every figure is read from a results file, not written by hand.</p>
<div class="who">signed in as <b class="me">{user_html}</b>
<span class="role">{role_html}</span>{tenant_picker}
&nbsp;<a class="out" href="/logout">sign out</a>
&nbsp;<span class="s">identity comes from the session, not from this page</span></div>
</header>
<div class="stats">{stats}</div>
<table>
<tr><th>document</th><th>supplier</th><th>why it was flagged</th><th>provenance</th>
<th>outcome</th><th>agent's reasoning</th><th>action</th></tr>
{''.join(trs)}
</table>
<footer>Generated {datetime.now():%d %b %Y %H:%M} from {source} &middot;
constructed corpus, synthetic purchase orders &mdash; labelled as such.<br>
Approvals are live only under <code>python3 dashboard/serve.py</code>; opening this file
directly shows the queue read-only.</footer>
<div id="ov"><button id="ovx" aria-label="close">&times;</button>
<div class="sheet"><div class="page-wrap"><div class="page" id="page"></div></div>
<div class="side" id="side"></div></div></div>
<script>
var TENANT = {tenant_json};

// The document viewer. Spans are drawn at their own bbox, so a reviewer sees where on
// the page a flagged value physically sits -- the same coordinates the span id encodes.
var ov = document.getElementById("ov");
var pageEl = document.getElementById("page");
var sideEl = document.getElementById("side");

function esc(t) {{
  var d = document.createElement("div"); d.textContent = t == null ? "" : t;
  return d.innerHTML;
}}

function closeOv() {{ ov.classList.remove("on"); }}
document.getElementById("ovx").addEventListener("click", closeOv);
ov.addEventListener("click", function (e) {{ if (e.target === ov) closeOv(); }});
document.addEventListener("keydown", function (e) {{
  if (e.key === "Escape") closeOv();
}});

function openDoc(docId) {{
  pageEl.innerHTML = "";
  sideEl.innerHTML = '<h2>' + esc(docId) + '</h2><div class="hash">loading\u2026</div>';
  ov.classList.add("on");

  fetch("/document?doc=" + encodeURIComponent(docId) + "&tenant=" + encodeURIComponent(TENANT))
    .then(function (r) {{ return r.json().then(function (j) {{ return [r.status, j]; }}); }})
    .then(function (p) {{
      var status = p[0], d = p[1];
      if (status !== 200) {{
        sideEl.innerHTML = '<h2>' + esc(docId) + '</h2><div class="hash">' +
          esc(d.error || ("HTTP " + status)) + "</div>";
        return;
      }}

      d.spans.forEach(function (sp) {{
        var b = sp.bbox, el = document.createElement("div");
        el.className = "sp" + (sp.flagged ? " flag" : "") +
                       (sp.fieldtype === "other" ? " note" : "");
        el.style.left = (b[0] * 100) + "%";
        el.style.top = (b[1] * 100) + "%";
        el.style.width = ((b[2] - b[0]) * 100) + "%";
        el.style.height = ((b[3] - b[1]) * 100) + "%";
        el.title = sp.span_id + "  \u00b7  " + (sp.fieldtype || "");
        el.textContent = sp.text;
        pageEl.appendChild(el);
      }});

      var h = '<h2>' + esc(d.doc_id) + '</h2>';
      h += '<div class="intact ' + (d.intact ? "y" : "n") + '">' +
           (d.intact ? "hash matches" : "hash differs") + "</div>";
      h += '<div class="hash">sha256 ' + esc(d.doc_hash) + "</div>";
      h += "<h3>supplier</h3><div>" + esc(d.vendor || "unknown") + "</div>";
      h += "<h3>why it was flagged</h3>";
      if (!d.findings.length) h += '<div class="fi"><div class="d">no findings</div></div>';
      d.findings.forEach(function (f) {{
        h += '<div class="fi"><div class="c">' + esc(f.code) + "</div>";
        h += '<div class="d">' + esc(f.detail || "") + "</div>";
        if (f.value) h += '<div class="v">' + esc(f.value) + "</div>";
        if (f.span_id) h += '<div class="sid">' + esc(f.span_id) + "</div>";
        h += "</div>";
      }});
      h += "<h3>the whole document</h3>" +
           '<div style="font-size:12px;color:#8b949e">' + d.spans.length +
           " spans. Everything the reader was shown, and nothing else.</div>";
      sideEl.innerHTML = h;
    }})
    .catch(function () {{
      sideEl.innerHTML = '<h2>' + esc(docId) +
        '</h2><div class="hash">no server \u2014 run: make serve</div>';
    }});
}}

document.querySelectorAll("button.doc").forEach(function (b) {{
  b.addEventListener("click", function () {{ openDoc(b.dataset.doc); }});
}});
document.querySelectorAll("button.ap").forEach(function (b) {{
  b.addEventListener("click", function () {{
    var doc = b.dataset.doc;
    var out = document.getElementById("res-" + doc);
    b.disabled = true; out.className = "s res"; out.textContent = "approving\\u2026";
    fetch("/approve", {{
      method: "POST", headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ doc_id: doc, tenant: TENANT }})
    }}).then(function (r) {{ return r.json().then(function (j) {{ return [r.status, j]; }}); }})
      .then(function (p) {{
        var status = p[0], j = p[1];
        if (status === 200) {{
          out.className = "s res ok";
          out.textContent = "APPROVED by " + j.approved_by;
        }} else {{
          out.className = "s res err";
          out.textContent = "REFUSED \\u2014 " + (j.error || status);
          b.disabled = false;
        }}
      }})
      .catch(function () {{
        out.className = "s res err";
        out.textContent = "no server \\u2014 run: make serve";
        b.disabled = false;
      }});
  }});
}});
</script>
"""


if __name__ == "__main__":
    main()
