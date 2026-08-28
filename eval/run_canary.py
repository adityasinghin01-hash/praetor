"""The canary, measured on the whole corpus instead of argued for.

Two questions, and they need different setups because they are different claims.

**How often does it fire when nothing is wrong?** Take every document, extract it
correctly (straight from the annotations, no model), and count firings. Every one is a
false positive, and each would cost a human touch. This is the number that decides
whether the check is affordable.

**Does it fire when the attack succeeds?** The canary only has anything to say once the
reader has already been fooled into pointing the privileged field at attacker-controlled
text -- which is the failure the resolver deliberately permits, because the span is real.
So we simulate exactly that: point `bank_account` at the prose span, on every document
that carries one, and count.

The second setup is a simulation and is labelled as one. It is not a measurement of how
often a model is fooled -- FINDINGS §1 is that number. It measures what happens after.

**Two populations, counted separately, and an earlier version of this script did not.**
`fieldtype: other` is the label for *any* free-text span. On this corpus 42 documents
carry one, but only **20** of those are an injected payload -- the other 22 are the
legitimate explanation notes `eval/make_invoices.py` writes to justify a deviation. The
first version counted all 42 as injections and reported "42 of 42 injected documents
caught", which overstated the attack corpus 2.1x. The canary itself was never wrong:
it never reads the text, so a note and a payload are the same situation to it, and all
42 fired. The label was wrong, not the mechanism. Both rows are printed now, and
`tests/test_canary.py` pins the injected count against the truth file.

    python eval/run_canary.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attacks.payloads import TAXONOMY  # noqa: E402
from praetor import canary  # noqa: E402
from praetor.docile_adapter import (load_annotation, span_kinds_of,  # noqa: E402
                                    spans_of, to_record)
from praetor.resolver import resolve  # noqa: E402

# A prose span whose text is exactly one of the payloads we planted. Identifying an
# injection by its text, rather than by its `other` label, is what separates the two
# populations -- and it agrees row for row with `injected` in constructed_truth.jsonl.
# Compared on the stripped text, because `spans_of()` strips: three payloads open
# with newlines and would otherwise never match themselves.
PAYLOAD_TEXTS = frozenset(p.text.strip() for p in TAXONOMY)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", default="data/constructed")
    args = ap.parse_args()

    docs = sorted(Path(args.annotations).glob("*.json"))
    if not docs:
        sys.exit(f"no annotations in {args.annotations}")

    clean_fired = clean_with_account = 0
    prose_docs = prose_resolved = prose_fired = 0
    injected_docs = injected_resolved = injected_fired = 0
    unlabelled = 0
    example = None

    for p in docs:
        ann, doc_hash = load_annotation(p)
        kinds = span_kinds_of(ann)
        spans = spans_of(ann, doc_hash)

        # 1. correct extraction -- anything that fires here is a false positive
        truth = to_record(ann, doc_hash, doc_id=p.stem)
        if truth.bank_account is not None:
            clean_with_account += 1
        fired = canary.check(truth, kinds)
        clean_fired += bool(fired)
        for f in fired:
            if f.code == "ORIGIN_UNKNOWN":
                unlabelled += 1

        # 2. the attack, simulated: the reader points the privileged field at a prose
        #    span. The span is real, so the resolver allows it -- by design.
        prose = [sid for sid, kind in kinds.items() if kind == "other"]
        if not prose:
            continue
        sid = prose[0]
        # Is this an injected payload, or one of the corpus's own explanation notes?
        # The canary cannot tell and must not need to; we count them apart so the
        # reported attack corpus is the real one.
        is_injection = any(spans.get(x, "") in PAYLOAD_TEXTS for x in prose)
        if is_injection:
            sid = next(x for x in prose if spans.get(x, "") in PAYLOAD_TEXTS)
            injected_docs += 1
        prose_docs += 1

        res = resolve({"bank_account": sid}, spans, doc_hash, p.stem)
        if res.record.bank_account is None:
            continue                      # resolver refused it; canary not reached
        prose_resolved += 1
        injected_resolved += is_injection
        hit = canary.check(res.record, kinds)
        if hit:
            prose_fired += 1
            injected_fired += is_injection
            if example is None and is_injection:
                example = f"{p.stem}: {hit[0].detail}"

    print("=" * 70)
    print(f"CANARY over {len(docs)} documents ({args.annotations})\n")
    print("1. Correct extraction -- every firing here is a false positive")
    print(f"   documents                        {len(docs)}")
    print(f"   with a bank account extracted    {clean_with_account}")
    print(f"   canary fired                     {clean_fired}")
    print(f"   of those, unlabelled origin      {unlabelled}")
    print(f"   false-positive rate              {clean_fired / len(docs):.4f}")

    print("\n2. Attack simulated -- privileged field pointed at a free-text span")
    print(f"   documents with a free-text span  {prose_docs}")
    print(f"   resolver accepted the span       "
          f"{prose_resolved} (it is a real span, by design)")
    print(f"   canary fired                     {prose_fired}")
    if prose_docs:
        print(f"   caught                           {prose_fired / prose_docs:.1%}")

    print("\n   of those, an injected payload rather than a legitimate note:")
    print(f"   documents carrying an injection  {injected_docs}")
    print(f"   resolver accepted the span       {injected_resolved}")
    print(f"   canary fired                     {injected_fired}")
    if injected_docs:
        print(f"   caught                           "
              f"{injected_fired / injected_docs:.1%}")
    print(f"   the remaining {prose_docs - injected_docs} are explanation notes this "
          f"corpus writes itself.\n   The canary cannot tell them apart -- it never "
          f"reads the text -- and does not need to.")
    if example:
        print(f"\n   e.g. {example[:110]}")

    print("\nNo model was called. Cost Rs 0.")


if __name__ == "__main__":
    main()
