"""Print the trace for one document: what happened to it, and where each value came from.

A trace you can only read after a cloud deployment is a trace you cannot use while
building, so spans go to a local file and this reads them back.

    PRAETOR_TRACE=1 python eval/run_adjudication.py --limit 5
    python eval/show_trace.py --doc V014_009

The column that matters is the taint one. It answers, from the trace alone, whether a
value that reached a decision came off a document nobody trusted.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praetor import trace  # noqa: E402

DIM, RESET, RED, GREEN, BLUE, YELLOW = "\033[2m", "\033[0m", "\033[31m", "\033[32m", "\033[34m", "\033[33m"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", help="show only this document")
    ap.add_argument("--file", default=None)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    spans = trace.read(args.file)
    if not spans:
        print("No spans recorded yet. Tracing is off unless you ask for it:\n"
              "  PRAETOR_TRACE=1 python eval/run_adjudication.py --limit 5")
        return

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for s in spans:
        by_doc[s["attributes"].get("praetor.doc_id", "(no document)")].append(s)

    docs = [args.doc] if args.doc else sorted(by_doc)
    shown = 0

    for doc in docs:
        rows = by_doc.get(doc)
        if not rows:
            print(f"no spans for {doc}")
            continue
        print(f"\n{doc}")
        for s in sorted(rows, key=lambda r: r["start"]):
            a = s["attributes"]
            tainted = a.get("praetor.tainted", a.get("praetor.account.tainted"))
            if tainted is True:
                mark = f"{RED}TAINTED{RESET}"
            elif tainted is False:
                mark = f"{GREEN}trusted{RESET}"
            else:
                mark = f"{DIM}   -   {RESET}"

            detail = ""
            if s["name"] == "extract":
                detail = (f"{a.get('praetor.spans_seen', 0)} spans off the document"
                          f"  {DIM}doc {a.get('praetor.doc_hash','')}{RESET}")
            elif s["name"] == "rules.evaluate":
                detail = f"{a.get('praetor.verdict','')}"
                if a.get("praetor.findings"):
                    detail += f"  {YELLOW}{a['praetor.findings']}{RESET}"
                detail += f"  {DIM}vs {a.get('praetor.peer_invoices',0)} prior invoices{RESET}"
            elif s["name"] == "resolve":
                detail = (f"{a.get('praetor.fields_resolved', 0)} resolved, "
                          f"{a.get('praetor.fields_rejected', 0)} rejected")
                if a.get("praetor.rejected"):
                    detail += f"  {RED}{a['praetor.rejected'][:70]}{RESET}"
            elif s["name"] == "gate.evaluate":
                detail = a.get("praetor.action", "")
                if a.get("praetor.findings"):
                    detail += f"  {YELLOW}{a['praetor.findings']}{RESET}"
            elif s["name"] == "adjudicate":
                detail = (f"agent said {a.get('praetor.agent_decision')} "
                          f"-> {a.get('praetor.decision')}")
                if a.get("praetor.overridden"):
                    detail += f"  {RED}OVERRIDDEN: {a.get('praetor.override_reason')}{RESET}"
            elif s["name"] == "gate.approve":
                detail = f"{GREEN}declassified by {a.get('praetor.approved_by')}{RESET}"

            span_id = a.get("praetor.span_id") or a.get("praetor.account.span_id", "")
            print(f"  {mark}  {BLUE}{s['name']:<14}{RESET} {detail}")
            if span_id:
                doc_hash = a.get("praetor.doc_hash") or a.get("praetor.account.doc_hash", "")
                print(f"           {DIM}{span_id}  doc {doc_hash}{RESET}")
            shown += 1
            if shown >= args.limit:
                print(f"\n{DIM}... {len(spans) - shown} more spans{RESET}")
                return

    print(f"\n{len(spans)} spans in {args.file or trace.TRACE_FILE}")


if __name__ == "__main__":
    main()
