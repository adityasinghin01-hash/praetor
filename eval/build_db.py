"""Load the file-based results into the database, and seed tenants and users.

The measurement pipeline still writes JSONL -- that is the evidence, it is committed in
results/, and `make demo` works from it alone with no database at all. This script takes
that evidence and populates the live store the review queue actually serves from.

Run it after `make rules` and `make adjudicate`:

    python eval/build_db.py                       # default tenant
    python eval/build_db.py --tenant borealis-retail --exceptions out/exc_b.jsonl

Idempotent: re-running replaces documents, findings and adjudications, and leaves
approvals alone. Approvals are the one thing a re-import must never touch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from praetor import auth, firestore_store, store
from praetor.docile_adapter import load_annotation

ROOT = Path(__file__).resolve().parents[1]

# Seed accounts, so a fresh clone has someone who can log in and approve. The password
# is printed on the sign-in page on purpose: a judge cloning this repo has no other way
# in, and pretending these are secrets would help nobody. Real deployments replace this
# seeding step with an identity provider.
DEMO_PASSWORD = "praetor"
SEED_USERS = [
    ("aditya@kiet", "Aditya", "approver"),
    ("reviewer@acme-industries.test", "AP Reviewer", "approver"),
    ("auditor@acme-industries.test", "Auditor", "viewer"),
]


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def pick(name: str) -> Path:
    """A fresh run in out/ wins; results/ is the committed measurement it falls back to."""
    fresh = ROOT / "out" / name
    return fresh if fresh.exists() else ROOT / "results" / name


from contextlib import nullcontext


def _maybe_tx(db, conn):
    """SQLite gets one transaction; Firestore writes are individually atomic."""
    return db.tx(conn) if hasattr(db, "tx") else nullcontext()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=store.DEFAULT_TENANT)
    ap.add_argument("--tenant-name", default=None)
    ap.add_argument("--exceptions", default=None,
                    help="defaults to out/ then results/ exc_constructed.jsonl")
    ap.add_argument("--adjudication", default=None)
    ap.add_argument("--annotations", default="data/constructed",
                    help="where the source documents live, recorded per document")
    ap.add_argument("--po-register", default="data/po_register.json")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    exc_path = Path(args.exceptions) if args.exceptions else pick("exc_constructed.jsonl")
    adj_path = Path(args.adjudication) if args.adjudication else pick("adjudication.jsonl")

    exceptions = {r["doc_id"]: r for r in load_jsonl(exc_path)}
    adjudications = {}
    for r in load_jsonl(adj_path):
        adjudications.setdefault(r["doc_id"], r)

    # PRAETOR_BACKEND=firestore sends the same load to Cloud Firestore instead.
    db = firestore_store if firestore_store.enabled() else store
    conn = db.connect() if db is firestore_store else db.connect(args.db)
    tenant = args.tenant
    print(f"backend: {'firestore' if db is firestore_store else 'sqlite'}")

    with _maybe_tx(db, conn):
        db.add_tenant(conn, tenant, args.tenant_name or tenant)
        for uid, name, role in SEED_USERS:
            db.add_user(conn, uid, name)
            db.grant(conn, uid, tenant, role)
            auth.set_password(conn, uid, DEMO_PASSWORD)

        # Purchase orders: the trusted record. Amounts land here too, which is what
        # finally lets the gate's reconciliation check do anything.
        reg = ROOT / args.po_register
        if reg.exists():
            data = json.loads(reg.read_text())
            orders = data.get("purchase_orders", []) if isinstance(data, dict) else data
            for o in orders:
                if isinstance(o, dict):
                    db.add_purchase_order(conn, tenant, o["po_ref"],
                                             o.get("amount"), o.get("currency"))
                else:
                    db.add_purchase_order(conn, tenant, o)

        for doc_id, e in exceptions.items():
            # Hash the source document itself. Deriving it from a flagged field's
            # evidence only works when something with a value was flagged -- a missing
            # field has no value to carry it, and eight documents came through as
            # "unknown" that way.
            src = ROOT / f"{args.annotations}/{doc_id}.json"
            doc_hash = load_annotation(src)[1] if src.exists() else "unknown"
            db.add_document(conn, tenant, doc_id,
                               doc_hash=doc_hash,
                               vendor_key=e.get("vendor_key"),
                               peer_invoices=e.get("n_peer_invoices", 0),
                               source_path=f"{args.annotations}/{doc_id}.json")
            db.add_findings(conn, tenant, doc_id,
                               e.get("findings", []), e.get("evidence", {}))

        for doc_id, a in adjudications.items():
            if doc_id not in exceptions:
                continue
            db.add_adjudication(conn, tenant, doc_id, a)

    if db is firestore_store:
        print(f"\ntenant           {tenant}")
        print(f"  documents      {len(exceptions)}")
        print(f"  adjudications  {len(adjudications)}")
        print(f"  users          {len(SEED_USERS)}  (password: {DEMO_PASSWORD})")
        print(f"\nfirestore -> project {conn.project}")
        return

    n_docs = conn.execute("SELECT COUNT(*) c FROM documents WHERE tenant_id=?",
                          (tenant,)).fetchone()["c"]
    n_adj = conn.execute("SELECT COUNT(*) c FROM adjudications WHERE tenant_id=?",
                         (tenant,)).fetchone()["c"]
    n_po = conn.execute("SELECT COUNT(*) c FROM purchase_orders WHERE tenant_id=?",
                        (tenant,)).fetchone()["c"]
    n_appr = conn.execute("SELECT COUNT(*) c FROM approvals WHERE tenant_id=?",
                          (tenant,)).fetchone()["c"]

    print(f"tenant           {tenant}")
    print(f"  documents      {n_docs}")
    print(f"  adjudications  {n_adj}")
    print(f"  purchase orders{n_po:>4}")
    print(f"  approvals kept {n_appr}")
    print(f"  users          {len(SEED_USERS)}  (password: {DEMO_PASSWORD})")
    print(f"\ndatabase -> {args.db or store.DB_PATH}")


if __name__ == "__main__":
    main()
