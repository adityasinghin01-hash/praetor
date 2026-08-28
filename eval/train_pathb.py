"""Fit the second extraction path, and hold it out BY LAYOUT.

Path B has one job: given every span in a document, say which one is the payable bank
account -- or abstain. It is fitted on the features in `praetor/features.py`, which
contain no words, so nothing written on a document can argue with it.

## Why the split is by layout and not by document

Grouping by document is the obvious guard against a span from a training document turning
up in the test set. It is not enough here, and the corpus itself proves it: FINDINGS §10
records a weak reader scoring F1 0.384 on a one-layout corpus purely because every
document's `payment_iban` span carried the *same coordinates*, so one memorised string
was correct 350 times.

A path that reads geometry is exactly the thing that failure mode flatters. Each of the
25 vendors keeps one of five page templates, so holding out a layout holds out five
vendors and 70 documents whose page geometry the fit has never seen. That measures
generalisation. Holding out documents alone would measure memorisation of five templates
and return a number near 1.000 for the wrong reason.

Five folds, one per layout. The reported figures are always from the fold that did not
see the test document's layout.

## What gets written

`praetor/pathb_weights.json` carries six fitted models: one per held-out layout, plus one
fitted on everything for a document whose layout is unknown. `eval/run_twopath.py` picks
the fold model that excludes the document's own layout, so no number in FINDINGS is
scored by a model that saw that layout.

## The optimiser

Iteratively reweighted least squares -- Newton's method on the logistic likelihood --
with an L2 ridge. Standard library only, about sixty lines, because a second path whose
fitting needs a compiled numerical stack is a second path nobody can check. It converges
in ten iterations rather than the tens of thousands gradient descent would need.

`tests/test_pathb.py` checks the fit against scikit-learn where scikit-learn is
installed, and skips where it is not. Hand-rolling a numerical method and never
comparing it to a reference is how you get a plausible wrong answer.

    python eval/train_pathb.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.distractors import variants  # noqa: E402
from praetor.features import (CONTENT_FEATURES, FEATURE_NAMES,  # noqa: E402
                              GEOMETRY_FEATURES, document_features)

# The span label that marks the positive class. Used ONLY as a training label -- Path B
# never sees a span's label at inference, which is what keeps it independent of
# praetor/canary.py, whose input is the label and nothing else.
POSITIVE_FIELDTYPE = "payment_iban"

# Which features the fit is allowed to use. `content` is what ships: geometry scored
# 0.208 alone, cost 0.020 in combination, and handed an adaptive attacker 67 documents
# it otherwise abstained on. See FINDINGS §17 -- and note that it was the layout
# hold-out this plan required that made the first two of those visible at all.
FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "content": CONTENT_FEATURES,
    "geometry": GEOMETRY_FEATURES,
    "all": FEATURE_NAMES,
}

RIDGE = 1.0          # L2 penalty. Never applied to the intercept.
ITERATIONS = 25
TOLERANCE = 1e-9


# --------------------------------------------------------------------------- linear algebra

def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting. Small, dense, and exact enough."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14:
            m[col][col] += 1e-9          # singular: nudge rather than crash
            piv = col
        m[col], m[piv] = m[piv], m[col]
        inv = 1.0 / m[col][col]
        for r in range(n):
            if r == col:
                continue
            f = m[r][col] * inv
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def fit(x: list[list[float]], y: list[int], weights: list[float] | None = None,
        ridge: float = RIDGE) -> list[float]:
    """Logistic regression by IRLS. Returns [intercept, *coefficients]."""
    n_feat = len(x[0])
    beta = [0.0] * (n_feat + 1)
    w_obs = weights or [1.0] * len(x)

    for _ in range(ITERATIONS):
        grad = [0.0] * (n_feat + 1)
        hess = [[0.0] * (n_feat + 1) for _ in range(n_feat + 1)]
        for row, target, ow in zip(x, y, w_obs):
            z = beta[0] + sum(b * v for b, v in zip(beta[1:], row))
            p = _sigmoid(z)
            r = ow * (target - p)
            s = ow * max(p * (1.0 - p), 1e-10)
            full = [1.0, *row]
            for i, fi in enumerate(full):
                if fi:
                    grad[i] += r * fi
                    hi = hess[i]
                    si = s * fi
                    for j, fj in enumerate(full):
                        if fj:
                            hi[j] += si * fj
        for i in range(1, n_feat + 1):        # ridge, never on the intercept
            grad[i] -= ridge * beta[i]
            hess[i][i] += ridge

        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < TOLERANCE:
            break
    return beta


# --------------------------------------------------------------------------- the corpus

def load_corpus(annotations: Path, variant: str = "distractor") -> list[dict]:
    """One row per document: its spans, its per-span vectors, its labels, its layout.

    `variant` selects the in-memory augmentation from `eval/distractors.py`. It defaults
    to `distractor` -- a VAT registration added to every document -- and that default is
    the whole reason this path works at all.

    Fitted on the corpus as it stands, Path B put all its weight on one feature, because
    exactly one token per page is shaped like an account number. The moment a second one
    appeared it had no tiebreaker and abstained on 342 of 342 documents: safe, and
    useless. Adding the distractor to the FIT rather than only to the test is the
    difference between a path that works on a real invoice and a path that works on ours.
    The corpus on disk is never modified. See FINDINGS §16.
    """
    docs = []
    for i, path in enumerate(sorted(annotations.glob("*.json"))):
        ann = json.loads(path.read_text())
        spans = ann.get("field_extractions", [])
        if not spans:
            continue
        spans = variants(spans, i)[variant]
        docs.append({
            "doc_id": path.stem,
            "layout": ann.get("layout", "unknown"),
            "index": i,
            "spans": spans,
            "x": document_features(spans),
            "y": [int(s.get("fieldtype") == POSITIVE_FIELDTYPE) for s in spans],
        })
    return docs


def restrict(docs: list[dict], names: Sequence[str]) -> list[dict]:
    """The same documents, with only the named features kept."""
    idx = [FEATURE_NAMES.index(n) for n in names]
    return [{**d, "x": [[row[i] for i in idx] for row in d["x"]]} for d in docs]


def flatten(docs: list[dict]) -> tuple[list[list[float]], list[int], list[float]]:
    """Spans from many documents, with the positive class up-weighted to parity.

    One span in nine is the payable account, so an unweighted fit is rewarded for
    answering 'no' to everything. Balancing is about the fit, not the decision: the
    decision is an argmax over one document's spans, where only the ordering matters.
    """
    x = [row for d in docs for row in d["x"]]
    y = [v for d in docs for v in d["y"]]
    pos = sum(y) or 1
    ratio = (len(y) - pos) / pos
    return x, y, [ratio if v else 1.0 for v in y]


def corpus_digest(docs: list[dict]) -> str:
    """A fingerprint of exactly what was fitted on.

    Weights are a derived artifact, and DECISIONS #16 exists because derived artifacts
    in this repo have gone stale four times without anything failing. This digest is
    checked by tests/test_pathb.py, so weights fitted on a corpus that no longer exists
    fail the build instead of quietly scoring something else.

    It hashes the **documents**, not the feature matrix. An earlier version hashed the
    vectors, which meant changing the feature set invalidated the digest and read as
    "the corpus moved" -- the check crying wolf about the one thing it is not for.
    What it must detect is the corpus changing underneath a fit, and that is the spans.
    """
    h = hashlib.sha256()
    for d in docs:
        h.update(d["doc_id"].encode())
        h.update(d["layout"].encode())
        for span in d["spans"]:
            h.update(str(span.get("fieldtype", "")).encode())
            h.update(str(span.get("text", "")).encode())
            h.update(",".join(f"{c:.4f}" for c in (span.get("bbox") or [])).encode())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- scoring

def evaluate(docs: list[dict], beta: list[float], min_p: float, min_margin: float,
             ) -> dict:
    """How the path behaves on whole documents: correct, wrong, or abstained."""
    from praetor.pathb import decide

    correct = wrong = abstained = no_truth = 0
    for d in docs:
        truth = next((s for s, v in zip(d["spans"], d["y"]) if v), None)
        pick = decide(d["x"], beta, min_p=min_p, min_margin=min_margin)
        if pick.index is None:
            abstained += 1
        elif truth is None:
            # No account on the page, so abstaining is the only correct answer and any
            # pick is wrong. Counting these as merely "without an account" hid two
            # documents where the supplier's VAT number was proposed as the payable
            # account -- see FINDINGS §16.
            wrong += 1
        elif d["spans"][pick.index] is truth:
            correct += 1
        else:
            wrong += 1
        no_truth += truth is None
    return {"documents": len(docs), "correct": correct, "wrong": wrong,
            "abstained": abstained, "without_an_account": no_truth}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    ap.add_argument("--out", default="praetor/pathb_weights.json")
    ap.add_argument("--min-p", type=float, default=0.50)
    ap.add_argument("--min-margin", type=float, default=0.20)
    ap.add_argument("--variant", default="distractor", choices=["baseline", "distractor"],
                    help="what the fit sees. `baseline` reproduces the useless fit.")
    ap.add_argument("--features", default="content", choices=sorted(FEATURE_SETS),
                    help="which features the fit may use. `content` is what ships.")
    args = ap.parse_args()

    names = FEATURE_SETS[args.features]
    docs = restrict(load_corpus(Path(args.annotations), args.variant), names)
    if not docs:
        sys.exit(f"no annotations in {args.annotations}")
    layouts = sorted({d["layout"] for d in docs})
    print(f"{len(docs)} documents, {sum(len(d['spans']) for d in docs)} spans, "
          f"{len(layouts)} layouts: {', '.join(layouts)}")
    print(f"variant: {args.variant}   features: {args.features} "
          f"({len(names)} of {len(FEATURE_NAMES)})\n")

    folds: dict[str, list[float]] = {}
    totals: dict[str, int] = defaultdict(int)
    print(f"{'held-out layout':<16} {'docs':>5} {'correct':>8} {'wrong':>6} "
          f"{'abstain':>8}  {'accuracy':>9}")
    print("-" * 60)
    for layout in layouts:
        train = [d for d in docs if d["layout"] != layout]
        test = [d for d in docs if d["layout"] == layout]
        beta = fit(*flatten(train))
        folds[layout] = beta
        r = evaluate(test, beta, args.min_p, args.min_margin)
        scored = r["documents"] - r["without_an_account"]
        for k, v in r.items():
            totals[k] += v
        print(f"{layout:<16} {r['documents']:>5} {r['correct']:>8} {r['wrong']:>6} "
              f"{r['abstained']:>8}  {r['correct'] / scored:>8.3f}")

    scored = totals["documents"] - totals["without_an_account"]
    print("-" * 60)
    print(f"{'ALL (held out)':<16} {totals['documents']:>5} {totals['correct']:>8} "
          f"{totals['wrong']:>6} {totals['abstained']:>8}  "
          f"{totals['correct'] / scored:>8.3f}")
    print(f"\ndocuments with no account to find: {totals['without_an_account']} "
          f"(a correct answer is an abstention)")

    full = fit(*flatten(docs))
    out = Path(args.out)
    out.write_text(json.dumps({
        "_comment": "Fitted by eval/train_pathb.py. `folds` is keyed by the layout HELD "
                    "OUT of that fit -- use the fold matching a document's own layout "
                    "so it is never scored by a model that saw it. `full` is fitted on "
                    "every layout and is for documents whose layout is unknown.",
        "feature_names": list(names),
        "features_excluded": [n for n in FEATURE_NAMES if n not in set(names)],
        "min_p": args.min_p,
        "min_margin": args.min_margin,
        "trained_on": {"annotations": str(args.annotations), "documents": len(docs),
                       "variant": args.variant, "features": args.features,
                       "layouts": layouts, "digest": corpus_digest(docs)},
        "folds": {k: [round(v, 8) for v in b] for k, b in folds.items()},
        "full": [round(v, 8) for v in full],
    }, indent=1) + "\n")
    print(f"\nwrote {out}  ({len(folds)} held-out folds + 1 full fit)")
    print("No model was called. Cost Rs 0.")


if __name__ == "__main__":
    main()
