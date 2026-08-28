"""Path B scores 1.000 on the corpus. This script is why that number must not be believed.

`eval/train_pathb.py` reports 342 of 342, held out by layout, zero wrong. An ablation
over the same folds says where it comes from:

    checksums / shape only      1.000
    character ratios only       0.997
    geometry only               0.205

The three structural features alone are perfect, and one of them is doing all the work:
`account_shape`, a regex for two letters, two digits and ten-to-thirty alphanumerics.
On this corpus **exactly one token per page has that shape, and it is the answer.** Path
B is a shape test wearing a fitted model's clothes, and the layout hold-out -- which is
methodologically right and which the plan required -- is barely being exercised, because
the component it protects against memorising contributes almost nothing.

Real invoices are not like that. They carry a VAT registration, a customer reference, an
order number: several tokens of the same shape, only one of which is payable. So this
script makes the corpus harder in the two ways that matter, and re-measures.

**Nothing here modifies the corpus.** Every document is augmented in memory at scoring
time, so no published figure moves and no file on disk changes. Regenerating the corpus
to make one component look better is how a number drifts while nobody is watching --
FINDINGS §5 already spent a correction on that.

Three runs:

  1. **baseline**   the corpus as it is.
  2. **distractor** a VAT registration added to every document: legitimate, printed by
     the supplier, the same shape as an account, and not payable. Geometry and ratios
     now have to do the work the shape test was doing.
  3. **adaptive**   an attacker who has read this file. Not prose -- a bare
     account-shaped token, placed where a payment field sits. This is the payload Path
     B is supposed to lose to, and reporting the number it loses by is the point.

    python eval/run_pathb_stress.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.distractors import ADAPTIVE_ACCOUNT, VARIANTS, variants  # noqa: E402
from praetor import canary  # noqa: E402
from praetor.pathb import extract  # noqa: E402
from praetor.types import Field, InvoiceRecord, Provenance  # noqa: E402


def _would_pay(spans: list[dict], index: int) -> bool:
    """Would this pick have reached a payment, or does something downstream stop it?

    Path B is one layer. The question that decides whether its failure matters is
    whether `praetor/canary.py` -- which reads the document's own label for the span and
    never its text -- refuses the origin anyway. This runs the real check rather than
    asserting what it would say.
    """
    span = spans[index]
    l, t, r, b = (list(span.get("bbox") or []) + [0.0, 0.0, 0.0, 0.0])[:4]
    sid = "p%d:%s" % (int(span.get("page", 0) or 0),
                      "_".join(f"{c:.4f}" for c in (l, t, r, b)))
    record = InvoiceRecord(doc_id="stress", bank_account=Field(
        value=str(span.get("text", "")), prov=Provenance(doc_hash="stress", span_id=sid)))
    kinds = {}
    for sp in spans:
        bl, bt, br, bb = (list(sp.get("bbox") or []) + [0.0, 0.0, 0.0, 0.0])[:4]
        kinds["p%d:%s" % (int(sp.get("page", 0) or 0),
                          "_".join(f"{c:.4f}" for c in (bl, bt, br, bb)))] = \
            str(sp.get("fieldtype", "") or "")
    return not canary.check(record, kinds)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    args = ap.parse_args()

    docs = []
    for i, path in enumerate(sorted(Path(args.annotations).glob("*.json"))):
        ann = json.loads(path.read_text())
        spans = ann.get("field_extractions", [])
        truth = next((s for s in spans if s["fieldtype"] == "payment_iban"), None)
        docs.append({"doc_id": path.stem, "layout": ann.get("layout", "unknown"),
                     "spans": spans, "truth": truth, "index": i})

    results: dict[str, dict[str, int]] = {}
    for name in VARIANTS:
        r = {"correct": 0, "wrong": 0, "abstained": 0, "took_the_attackers_span": 0,
             "took_the_vat_number": 0, "no_account": 0, "would_have_paid": 0}
        for d in docs:
            spans = variants(d["spans"], d["index"])[name]
            # Through extract(), not a copy of it: the fold selection, the feature
            # selection and the thresholds must be the ones that actually ship.
            pick = extract(spans, layout=d["layout"])
            if d["truth"] is None:
                # A document with no account to find. Abstaining is the only correct
                # answer, so ANY pick here is wrong and is counted as wrong.
                #
                # It was not, until 28 Aug. These documents were tallied only under
                # `no_account`, so two documents where Path B proposed the supplier's
                # VAT number as the payable account showed up as `-> VAT 0`. A
                # population counted in the wrong column is the same defect FINDINGS §12
                # corrected in the canary, found the same way: by checking the
                # arithmetic instead of the summary.
                r["no_account"] += 1
                if pick.index is None:
                    r["abstained"] += 1
                    continue
                r["wrong"] += 1
                chosen = spans[pick.index]
                if chosen["text"] == ADAPTIVE_ACCOUNT:
                    r["took_the_attackers_span"] += 1
                r["took_the_vat_number"] += chosen["fieldtype"] == "vendor_tax_id"
                r["would_have_paid"] += _would_pay(spans, pick.index)
                continue
            if pick.index is None:
                r["abstained"] += 1
            elif spans[pick.index] is d["truth"]:
                r["correct"] += 1
            else:
                r["wrong"] += 1
                chosen = spans[pick.index]
                if chosen["text"] == ADAPTIVE_ACCOUNT:
                    r["took_the_attackers_span"] += 1
                r["took_the_vat_number"] += chosen["fieldtype"] == "vendor_tax_id"
                r["would_have_paid"] += _would_pay(spans, pick.index)
        results[name] = r

    n = len(docs)
    scored = n - results["baseline"]["no_account"]
    print("=" * 74)
    print(f"PATH B under stress -- {n} documents, scored by the fold that did not see "
          f"their layout\n")
    print(f"{'':<16} {'correct':>7} {'wrong':>6} {'abstain':>8} {'accuracy':>9}"
          f"  {'-> VAT':>7} {'-> attacker':>12} {'PAID':>6}")
    print("-" * 74)
    for name in VARIANTS:
        r = results[name]
        print(f"{name:<16} {r['correct']:>7} {r['wrong']:>6} {r['abstained']:>8} "
              f"{r['correct'] / scored:>9.3f}  {r['took_the_vat_number']:>7} "
              f"{r['took_the_attackers_span']:>12} {r['would_have_paid']:>6}")
    print("-" * 74)
    print("\n'-> attacker' is Path B beaten. 'PAID' is Path B beaten AND the origin "
          "check\nin praetor/canary.py failing to refuse the span anyway -- the only "
          "column that\nwould have moved money.")
    print(f"\n{results['baseline']['no_account']} documents have no account to find; "
          f"abstaining is the only correct answer there, so any pick counts as wrong.")
    print("\nNo corpus file was written. No model was called. Cost Rs 0.")

    out = Path("out/pathb_stress.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"documents": n, "scored": scored,
                               "results": results}, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
