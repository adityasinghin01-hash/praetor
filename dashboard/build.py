"""Build the review dashboard from real result files.

This is what appears in the demo video: the queue a human actually works. It reads
out/exceptions or out/adjudication.jsonl plus the ground truth, and renders a single
self-contained HTML file with no external dependencies.

Every number on the page comes from a file in out/. Nothing is hardcoded.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main() -> None:
    truth = {r["doc_id"]: r for r in load_jsonl(ROOT / "data/constructed_truth.jsonl")}
    adj = {}
    for r in load_jsonl(ROOT / "out/adjudication.jsonl"):
        adj.setdefault(r["doc_id"], r)
    exceptions = {r["doc_id"]: r for r in load_jsonl(ROOT / "out/exc_constructed.jsonl")}

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
            "decision": a["decision"],
            "agent_decision": a["agent_decision"],
            "overridden": a["overridden"],
            "reason": a.get("reason", ""),
            "correct": t.get("correct_action", "?"),
            "injected": bool(t.get("injected")),
        })

    total = len(rows)
    resolved = [r for r in rows if r["decision"] == "resolve"]
    escalated = [r for r in rows if r["decision"] == "escalate"]
    overrides = [r for r in rows if r["overridden"]]
    wrong = [r for r in resolved if r["correct"] == "escalate"]
    right = [r for r in resolved if r["correct"] == "resolve"]
    prec = len(right) / len(resolved) if resolved else 0.0

    out = ROOT / "dashboard" / "index.html"
    out.write_text(render(rows, total, resolved, escalated, overrides, wrong, prec))
    print(f"wrote {out}")
    print(f"  {total} exceptions | {len(resolved)} resolved | {len(escalated)} escalated "
          f"| {len(overrides)} gate override(s) | precision {prec:.3f}")


def render(rows, total, resolved, escalated, overrides, wrong, prec) -> str:
    def card(label, value, sub="", tone=""):
        return (f'<div class="card {tone}"><div class="v">{value}</div>'
                f'<div class="l">{label}</div><div class="s">{sub}</div></div>')

    stats = "".join([
        card("flagged by rules", total, "every one would reach a human"),
        card("cleared by agent", len(resolved), "no human needed", "good"),
        card("sent to a human", len(escalated), "with evidence attached"),
        card("resolve precision", f"{prec*100:.1f}%", f"{len(wrong)} wrong of {len(resolved)}",
             "good" if not wrong else "warn"),
        card("gate overrides", len(overrides), "agent fooled, gate held", "crit"),
    ])

    trs = []
    for r in rows:
        badge = ('<span class="b crit">GATE OVERRODE</span>' if r["overridden"]
                 else '<span class="b good">cleared</span>' if r["decision"] == "resolve"
                 else '<span class="b">escalated</span>')
        inj = '<span class="b warn">injected</span>' if r["injected"] else ""
        codes = " ".join(f'<span class="code">{c}</span>' for c in r["codes"])
        detail = "<br>".join(f'<span class="d">{f["code"]}</span> {f["detail"]}'
                             for f in r["findings"]) or "&mdash;"
        trs.append(f"""<tr>
<td class="mono">{r['doc_id']}</td>
<td>{r['vendor'][:34]}<div class="s">{r['peers']} prior invoices</div></td>
<td>{codes}<div class="s">{detail}</div></td>
<td>{badge} {inj}</td>
<td class="reason">{r['reason'][:150]}</td></tr>""")

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
header p {{ margin:6px 0 0; color:var(--dim); font-size:13px; }}
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
.reason {{ color:var(--dim); font-size:12.5px; max-width:340px; }}
footer {{ padding:0 32px 40px; color:var(--dim); font-size:12px; }}
</style>
<header>
<h1>PRAETOR &mdash; invoice review queue</h1>
<p>Rules flag; the agent adjudicates; the policy gate has the last word.
Every figure below is read from a results file, not written by hand.</p>
</header>
<div class="stats">{stats}</div>
<table>
<tr><th>document</th><th>supplier</th><th>why it was flagged</th>
<th>outcome</th><th>agent's reasoning</th></tr>
{''.join(trs)}
</table>
<footer>Generated {datetime.now():%d %b %Y %H:%M} from out/adjudication.jsonl &middot;
constructed corpus, synthetic purchase orders &mdash; labelled as such.</footer>
"""


if __name__ == "__main__":
    main()
