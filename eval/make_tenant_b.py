"""A second client company's books, sharing suppliers with the first and paying them
somewhere else.

`data/constructed` is one tenant: 25 suppliers, 350 invoices, and every published number
in FINDINGS is scored against it. It is frozen. This writes a **second** tenant beside it
rather than regenerating it, because a corpus that moves under a published figure is the
failure [FINDINGS §5](../FINDINGS.md) already spent a correction on.

`eval/make_invoices.py` is imported, not modified, for the same reason.

## Why the overlap is the point

`praetor/tenancy.py` exists for one specific, expensive failure: two clients of the same
AP processor both buy from the same supplier and hold **different** accounts for it. A
vendor master keyed on supplier name answers "yes, we know this account" about the wrong
company's books.

Until now that scenario lived only in `tests/test_tenancy.py` as three hand-written
fixtures. Here it is a corpus: **five of tenant B's suppliers are tenant A's suppliers,
by name, paid at different accounts.** The isolation claim can then be measured on
documents rather than demonstrated on a fixture.

Everything is derived from tenant A's committed corpus plus a fixed seed, so it
regenerates bit for bit and nothing about tenant A changes.

    python eval/make_tenant_b.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.make_invoices import (CURRENCIES, DEVIATIONS, LAYOUT_NAMES,  # noqa: E402
                                STREETS, CITIES, build, make_vendors, to_annotation)

TENANT = "borealis"          # tenant A, the existing corpus, is "acme"
SHARED = 5                   # suppliers both clients buy from


def tenant_a_vendors(annotations: Path) -> list[str]:
    """Supplier names as tenant A's documents actually print them.

    Read from the corpus rather than regenerated, so the two tenants cannot drift apart
    if the generator's name pool is ever edited.
    """
    names: list[str] = []
    for path in sorted(annotations.glob("*.json")):
        for span in json.loads(path.read_text())["field_extractions"]:
            if span["fieldtype"] == "vendor_name" and span["text"] not in names:
                names.append(span["text"])
    return names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-a", default="data/constructed")
    ap.add_argument("--out", default="data/constructed_borealis")
    ap.add_argument("--vendors", type=int, default=10)
    ap.add_argument("--per-vendor", type=int, default=8)
    ap.add_argument("--deviation-rate", type=float, default=0.18)
    ap.add_argument("--explained-rate", type=float, default=0.55)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    shared_names = tenant_a_vendors(ROOT / args.tenant_a)[:SHARED]
    if len(shared_names) < SHARED:
        sys.exit(f"tenant A has only {len(shared_names)} suppliers; need {SHARED}")

    vendors = make_vendors(args.vendors, rng)
    # The overlap. Same supplier, same client-facing name, a DIFFERENT account -- which
    # is the situation praetor/tenancy.py refuses to let a shared master answer.
    for i, name in enumerate(shared_names):
        vendors[i]["name"] = name
        vendors[i]["shared_with_tenant_a"] = True
    for i, v in enumerate(vendors):
        v["layout"] = LAYOUT_NAMES[i % len(LAYOUT_NAMES)]

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()

    truth_rows = []
    for v in vendors:
        for seq in range(args.per_vendor):
            dev = None
            explained = False
            if seq >= 3 and rng.random() < args.deviation_rate:
                dev = rng.choice(DEVIATIONS)
                explained = rng.random() < args.explained_rate
            fields, truth = build(v, seq, rng, dev, explained)
            doc_id = f"B{v['key'][1:]}_{seq:03d}"
            annotation = to_annotation(fields, None, v["layout"],
                                       random.Random(f"{args.seed}:{doc_id}"))
            annotation["tenant_id"] = TENANT
            (out / f"{doc_id}.json").write_text(json.dumps(annotation))
            truth_rows.append({"doc_id": doc_id, "tenant_id": TENANT,
                               "vendor_key": v["key"], "vendor_name": v["name"],
                               "layout": v["layout"],
                               "shared_with_tenant_a": bool(
                                   v.get("shared_with_tenant_a")),
                               "injected": False, **truth})

    truth_path = out.parent / f"{out.name}_truth.jsonl"
    with truth_path.open("w") as fh:
        for row in truth_rows:
            fh.write(json.dumps(row) + "\n")

    shared_docs = sum(1 for r in truth_rows if r["shared_with_tenant_a"])
    print(f"wrote {len(truth_rows)} invoices for tenant {TENANT!r} to {out}")
    print(f"  suppliers:                  {args.vendors} x {args.per_vendor}")
    print(f"  shared with tenant 'acme':  {SHARED} suppliers, {shared_docs} documents")
    for name in shared_names:
        print(f"      {name}")
    print(f"\n  Each shared supplier is paid at a DIFFERENT account than tenant A pays "
          f"it.\n  That is the case praetor/tenancy.py exists for, now in a corpus "
          f"rather than a fixture.")
    print(f"\n  truth: {truth_path}")
    print("  tenant A's corpus was read and not written. No model was called. Cost Rs 0.")


if __name__ == "__main__":
    main()
