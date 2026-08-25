"""Derive each supplier's 'normal' from their own real invoices.

Nothing here is invented. Every value is the mode or a percentile of real documents
in the corpus, which is what lets us say the exceptions we later find are DISCOVERED
rather than injected.

Leakage guard: we store per-document observations rather than a pre-computed pattern,
so that find_exceptions.py can rebuild a vendor's pattern EXCLUDING the document under
test (leave-one-out). Without that, every invoice contributes to the norm it is judged
against, and nothing ever looks abnormal.

Usage:
    python eval/build_vendor_master.py --annotations data/docile/annotations \
        --out out/vendor_master.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import quantiles

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praetor.docile_adapter import load_annotation, to_record  # noqa: E402
from praetor.types import VendorPattern  # noqa: E402

MIN_INVOICES = 3  # below this a "pattern" is noise, not a norm


def vendor_key(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def build(annotation_dir: str | Path) -> dict[str, list[dict]]:
    """vendor_key -> list of per-document observations."""
    obs: dict[str, list[dict]] = defaultdict(list)
    paths = sorted(Path(annotation_dir).glob("*.json"))
    for p in paths:
        ann, doc_hash = load_annotation(p)
        rec = to_record(ann, doc_hash, doc_id=p.stem)
        vk = vendor_key(rec.get("vendor_name"))
        if not vk:
            continue
        obs[vk].append({
            "doc_id": rec.doc_id,
            "bank_account": rec.get("bank_account"),
            "invoice_number": rec.get("invoice_number"),
            "currency": rec.get("currency"),
            "tax_rate": rec.get("tax_rate"),
            "vendor_address": rec.get("vendor_address"),
            "amount_total": rec.get("amount_total"),
        })
    return dict(obs)


def _mode(values: list[str | None]) -> str | None:
    vals = [v for v in values if v]
    if not vals:
        return None
    return max(set(vals), key=vals.count)


def _amount(v: str | None) -> float | None:
    if not v:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", v.replace(",", "")))
    except ValueError:
        return None


def pattern_from(vk: str, rows: list[dict], exclude_doc: str | None = None) -> VendorPattern:
    """Materialise a pattern, optionally leaving one document out."""
    rows = [r for r in rows if r["doc_id"] != exclude_doc]
    amounts = sorted(a for a in (_amount(r["amount_total"]) for r in rows) if a is not None)

    p05 = p95 = None
    if len(amounts) >= 4:
        qs = quantiles(amounts, n=20)   # 5% steps
        p05, p95 = qs[0], qs[-1]
    elif amounts:
        p05, p95 = amounts[0], amounts[-1]

    return VendorPattern(
        vendor_key=vk,
        n_invoices=len(rows),
        bank_accounts={r["bank_account"] for r in rows if r["bank_account"]},
        seen_invoice_numbers={r["invoice_number"] for r in rows if r["invoice_number"]},
        modal_currency=_mode([r["currency"] for r in rows]),
        modal_tax_rate=_mode([r["tax_rate"] for r in rows]),
        modal_address=_mode([r["vendor_address"] for r in rows]),
        amount_p05=p05,
        amount_p95=p95,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--out", default="out/vendor_master.json")
    args = ap.parse_args()

    obs = build(args.annotations)
    usable = {k: v for k, v in obs.items() if len(v) >= MIN_INVOICES}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obs, indent=1))

    print(f"vendors seen:            {len(obs)}")
    print(f"vendors with >= {MIN_INVOICES} invoices: {len(usable)}")
    print(f"documents covered:       {sum(len(v) for v in usable.values())}")
    if usable:
        top = sorted(usable.items(), key=lambda kv: -len(kv[1]))[:5]
        print("\nlargest vendors:")
        for k, v in top:
            print(f"  {k[:44]:46} {len(v):4} invoices")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
