"""Two clients, shared suppliers, different accounts — what isolation is actually worth.

`praetor/tenancy.py` refuses to let one client's vendor master vouch for another's
invoice, and `DECISIONS.md` #7 records the cost: no cross-client intelligence at all.
Until now both the bug and the defence lived in `tests/test_tenancy.py` as three
hand-written fixtures. `eval/make_tenant_b.py` turns that into a corpus — a second client
company, `borealis`, that buys from six of `acme`'s suppliers and pays every one of them
at a different account.

Two questions, measured rather than argued:

**1. What does a merged vendor master actually get wrong?** For every shared supplier,
take one of that client's real invoices and substitute the *other* client's account for
the same supplier. That is invoice-redirection fraud with a twist: the account is
genuine, it is really that supplier's, and it belongs to somebody else's books. Score it
with the isolated master and with a merged one.

**2. What does the refusal network add back?** A person at one client refuses an account.
Measure what the other client sees on an invoice carrying it — and confirm the direction
never reverses.

    python eval/run_tenancy.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.build_vendor_master import build, vendor_key  # noqa: E402
from praetor import refusal  # noqa: E402
from praetor.docile_adapter import load_annotation, to_record  # noqa: E402
from praetor.gate import Action, evaluate  # noqa: E402
from praetor.tenancy import CrossTenantError, VendorMaster  # noqa: E402
from praetor.types import VendorPattern  # noqa: E402

SALT = "praetor-demo-salt"      # a deployment supplies its own; there is no default


def master_for(tenant: str, annotations: Path, into: VendorMaster) -> None:
    for vk, rows in build(annotations).items():
        into.add(tenant, VendorPattern(
            vendor_key=vk, n_invoices=len(rows),
            bank_accounts={r["bank_account"] for r in rows if r["bank_account"]}))


def merged_pattern(a: VendorMaster, b: VendorMaster, vk: str) -> VendorPattern:
    """The bug, built deliberately: one bucket holding both clients' accounts."""
    accounts: set[str] = set()
    n = 0
    for m, t in ((a, "acme"), (b, "borealis")):
        p = m.pattern_for(t, vk)
        if p:
            accounts |= p.bank_accounts
            n += p.n_invoices
    return VendorPattern(vendor_key=vk, tenant_id=None, n_invoices=n,
                         bank_accounts=accounts)


def load_docs(annotations: Path) -> list[tuple[str, object]]:
    out = []
    for p in sorted(annotations.glob("*.json")):
        ann, doc_hash = load_annotation(p)
        out.append((p.stem, to_record(ann, doc_hash, p.stem)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-a", default="data/constructed")
    ap.add_argument("--tenant-b", default="data/constructed_borealis")
    args = ap.parse_args()

    a_dir, b_dir = ROOT / args.tenant_a, ROOT / args.tenant_b
    if not b_dir.exists():
        sys.exit(f"{b_dir} missing. Run: python eval/make_tenant_b.py")

    isolated = VendorMaster()
    master_for("acme", a_dir, isolated)
    master_for("borealis", b_dir, isolated)

    a_keys = set(isolated.vendor_keys("acme"))
    b_keys = set(isolated.vendor_keys("borealis"))
    shared = sorted(a_keys & b_keys)

    print("=" * 74)
    print("TWO TENANTS\n")
    print(f"  acme      {len(a_keys):>3} suppliers, {len(list(a_dir.glob('*.json'))):>4} invoices")
    print(f"  borealis  {len(b_keys):>3} suppliers, {len(list(b_dir.glob('*.json'))):>4} invoices")
    print(f"  suppliers in both sets of books: {len(shared)}")

    # ---------------------------------------------------------------- 1. isolation
    print("\n" + "-" * 74)
    print("1. A real account, from the wrong client's books, on a real invoice\n")
    print("   The account is genuine and really is that supplier's. It is simply not the")
    print("   one THIS client has ever paid them at. Isolated must escalate; merged is")
    print("   the bug.\n")

    trials = wrong = right = 0
    example = None
    for vk in shared:
        for tenant, other, docs in (("acme", "borealis", load_docs(a_dir)),
                                    ("borealis", "acme", load_docs(b_dir))):
            mine = isolated.pattern_for(tenant, vk)
            theirs = isolated.pattern_for(other, vk)
            if not mine or not theirs:
                continue
            substitute = sorted(theirs.bank_accounts - mine.bank_accounts)
            doc = next((d for _, d in docs
                        if vendor_key(d.get("vendor_name")) == vk
                        and d.bank_account is not None), None)
            if not substitute or doc is None:
                continue

            doc.tenant_id = tenant
            doc.bank_account.__dict__["value"] = substitute[0]
            trials += 1

            isolated_decision = evaluate(doc, mine)
            merged_decision = evaluate(doc, merged_pattern(isolated, isolated, vk))
            right += isolated_decision.action is Action.ESCALATE
            wrong += merged_decision.action is not Action.ESCALATE
            if example is None and merged_decision.action is not Action.ESCALATE:
                example = (tenant, vk, substitute[0], other)

    print(f"   trials (one per shared supplier, per direction)   {trials}")
    print(f"   isolated master escalates                        {right} / {trials}")
    print(f"   MERGED master proposes payment anyway            {wrong} / {trials}")
    if example:
        t, vk, acct, other = example
        print(f"\n   e.g. {t} is shown {acct}")
        print(f"        for '{vk}'. It is {other}'s account for that same supplier.")
        print(f"        Isolated: escalate. Merged: pay.")

    # The second mechanism: even handed the wrong pattern, the gate refuses to run.
    crossed = 0
    for vk in shared[:1]:
        doc = next(d for _, d in load_docs(a_dir)
                   if vendor_key(d.get("vendor_name")) == vk)
        doc.tenant_id = "acme"
        try:
            evaluate(doc, isolated.pattern_for("borealis", vk))
        except CrossTenantError:
            crossed += 1
    print(f"\n   gate raises CrossTenantError when handed the other tenant's pattern: "
          f"{'yes' if crossed else 'NO'}")

    # ---------------------------------------------------------------- 2. the network
    print("\n" + "-" * 74)
    print("2. The refusal network: what a warning is allowed to do\n")

    net = refusal.RefusalNetwork(salt=SALT)
    acme_docs = load_docs(a_dir)

    # The case that matters. Pick an account acme has PAID before -- it is in their
    # vendor master, so acme would propose payment with no findings at all. Then a
    # person at borealis refuses it, which is what happens when an account a supplier
    # used legitimately is later found to be compromised.
    payable = None
    for doc_id, doc in acme_docs:
        doc.tenant_id = "acme"
        vk = vendor_key(doc.get("vendor_name"))
        pattern = isolated.pattern_for("acme", vk)
        if pattern and evaluate(doc, pattern).action is Action.PROPOSE_PAY:
            payable = (doc_id, doc, pattern, doc.bank_account.value)
            break
    if payable is None:
        sys.exit("no acme invoice is currently payable; nothing to demonstrate")

    doc_id, doc, pattern, account = payable
    before = evaluate(doc, pattern)
    net.record("borealis", account)
    after = refusal.apply(before, net.check(doc, asking_tenant="acme"))

    print("   An account acme has paid before, later refused by a person at borealis:\n")
    print(f"   invoice              {doc_id}")
    print(f"   before the network   {before.action.value:<12} {before.codes or 'no findings'}")
    print(f"   after  the network   {after.action.value:<12} {after.codes}")
    print(f"   findings removed     {len(set(before.codes) - set(after.codes))}"
          f"   <- must be 0, always")
    print(f"\n   The network turned a payment into a question. It has no mechanism for")
    print(f"   the reverse: `apply` only appends, and only a person can approve.")

    # ---- what it costs, on the same corpus
    flipped = would_pay = 0
    for _, other in acme_docs:
        other.tenant_id = "acme"
        vk = vendor_key(other.get("vendor_name"))
        pat = isolated.pattern_for("acme", vk)
        if pat is None:
            continue
        base = evaluate(other, pat)
        if base.action is not Action.PROPOSE_PAY:
            continue
        would_pay += 1
        if refusal.apply(base, net.check(other, asking_tenant="acme")).action \
                is Action.ESCALATE:
            flipped += 1

    print(f"\n   COST, on acme's whole corpus, from that ONE refusal:")
    print(f"     invoices acme would have paid       {would_pay}")
    print(f"     now sent to a person                {flipped}")
    print(f"     one refusal cost {flipped} human touches at another client. A client who")
    print(f"     refuses carelessly spends other clients' attention; the asymmetry is")
    print(f"     that it cannot spend their money.")
    print(f"\n     Read `{would_pay}` carefully: the vendor master here is built from")
    print(f"     the same corpus it scores, so every account is 'known' by construction")
    print(f"     (DECISIONS #12 says why that derivation is fine for measuring a rule")
    print(f"     and wrong as a trust boundary). The load-bearing number is {flipped}.")

    # And the direction that must never work. Deliberately an account NOBODY refused --
    # picking the first invoice with an account would have picked the refused one.
    clean = next(d for _, d in load_docs(a_dir)
                 if d.bank_account is not None and d.bank_account.value != account)
    clean.tenant_id = "acme"
    clean_pattern = isolated.pattern_for("acme", vendor_key(clean.get("vendor_name")))
    base = evaluate(clean, clean_pattern)
    still = refusal.apply(base, net.check(clean, asking_tenant="acme"))
    print(f"\n   an account NOBODY refused is unaffected: "
          f"{base.action.value} -> {still.action.value}")
    print(f"   the network holds {len(net._by_fingerprint)} fingerprint(s) and no "
          f"account numbers")

    print("\nNo model was called. Cost Rs 0.")


if __name__ == "__main__":
    main()
