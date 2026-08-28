"""The same store, on Cloud Firestore.

Why this exists in two forms. SQLite keeps `make demo` runnable by anyone with no
account, no card and no network, which is the property that lets a judge reproduce every
number in this repository. Firestore is Google Cloud infrastructure, which the hackathon
requires and which a laptop database is not. Neither replaces the other, so the store has
two backends and the default stays local.

    PRAETOR_BACKEND=firestore make serve

The interface is deliberately identical to praetor/store.py. Everything above this layer
-- the approve path, the queue, the dashboard -- is written against that interface and
does not know which backend it is talking to. That is the point of having put all state
behind one module in the first place.

What is *not* identical, and matters:

Firestore has no multi-column primary key, so the one-approval-per-document rule cannot
be a schema constraint the way `PRIMARY KEY (tenant_id, doc_id)` is in SQLite. Here it is
enforced by a transaction that reads the approval document and aborts if it exists.
Firestore transactions are serialisable, so this is still a real guarantee rather than a
check-then-write race -- but it is enforced by code rather than by the schema, and that
is a weaker place for it to live. Stated rather than glossed over.

Runs on the Firebase Spark plan: no card, no billing account.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

try:  # pragma: no cover - depends on whether the SDK is installed
    from google.cloud import firestore
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

from praetor import store
from praetor.store import ROLES, AlreadyApproved, NotEscalated

# One collection per entity, each document keyed by "<tenant>:<doc_id>" so a scan is
# never needed to scope a read to one client.
DOCS, FINDINGS, ADJ, APPROVALS, TENANTS, USERS, MEMBERS, POS, SESSIONS = (
    "documents", "findings", "adjudications", "approvals",
    "tenants", "users", "memberships", "purchase_orders", "sessions")
TRUSTED = "trusted_accounts"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key(tenant_id: str, doc_id: str) -> str:
    return f"{tenant_id}:{doc_id}"


def enabled() -> bool:
    return os.environ.get("PRAETOR_BACKEND", "").lower() == "firestore"


def connect(project: str | None = None):
    """A Firestore client. Credentials come from the environment, never from code.

    Set GOOGLE_APPLICATION_CREDENTIALS to a service-account key, or run
    `gcloud auth application-default login`. See docs/FIRESTORE.md.
    """
    if not AVAILABLE:
        raise RuntimeError(
            "google-cloud-firestore is not installed. pip install google-cloud-firestore")
    return firestore.Client(project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"))


# ---------------------------------------------------------------- writes

def add_tenant(db, tenant_id: str, name: str | None = None) -> None:
    db.collection(TENANTS).document(tenant_id).set(
        {"id": tenant_id, "name": name or tenant_id, "created_at": now()}, merge=True)


def add_user(db, user_id: str, name: str | None = None) -> None:
    uid = user_id.strip().lower()
    db.collection(USERS).document(uid).set(
        {"id": uid, "name": name, "created_at": now()}, merge=True)


def grant(db, user_id: str, tenant_id: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    uid = user_id.strip().lower()
    db.collection(MEMBERS).document(f"{uid}:{tenant_id}").set(
        {"user_id": uid, "tenant_id": tenant_id, "role": role})


def set_password_hash(db, user_id: str, password_hash: str) -> None:
    db.collection(USERS).document(user_id.strip().lower()).set(
        {"password_hash": password_hash}, merge=True)


def add_document(db, tenant_id, doc_id, doc_hash, vendor_key=None,
                 peer_invoices=0, source_path=None) -> None:
    db.collection(DOCS).document(_key(tenant_id, doc_id)).set({
        "tenant_id": tenant_id, "doc_id": doc_id, "doc_hash": doc_hash,
        "vendor_key": vendor_key, "peer_invoices": int(peer_invoices or 0),
        "source_path": str(source_path) if source_path else None,
        "ingested_at": now(),
    })


def add_findings(db, tenant_id, doc_id, findings, evidence=None) -> None:
    evidence = evidence or {}
    rows = []
    for f in findings:
        ev = evidence.get(f["field"], {})
        rows.append({
            "code": f["code"], "field": f["field"], "detail": f.get("detail"),
            "value": ev.get("value"), "span_id": ev.get("span_id"),
            "tainted": bool(ev.get("tainted", True)),
        })
    db.collection(FINDINGS).document(_key(tenant_id, doc_id)).set({
        "tenant_id": tenant_id, "doc_id": doc_id, "rows": rows})


def add_adjudication(db, tenant_id, doc_id, row) -> None:
    db.collection(ADJ).document(_key(tenant_id, doc_id)).set({
        "tenant_id": tenant_id, "doc_id": doc_id,
        "decision": row["decision"],
        "agent_decision": row.get("agent_decision", row["decision"]),
        "overridden": bool(row.get("overridden")),
        "override_reason": row.get("override_reason"),
        "reason": row.get("reason"), "model": row.get("model"), "at": now(),
    })


def add_purchase_order(db, tenant_id, po_ref, amount=None, currency=None) -> None:
    ref = po_ref.strip().upper()
    db.collection(POS).document(f"{tenant_id}:{ref}").set({
        "tenant_id": tenant_id, "po_ref": ref, "amount": amount, "currency": currency})


def record_approval(db, tenant_id, doc_id, approved_by, codes) -> dict:
    """Write the approval, refusing a duplicate or a document nobody escalated.

    Firestore has no composite primary key, so uniqueness cannot be a constraint here the
    way it is in SQLite. A transaction gets us the same guarantee -- Firestore
    transactions are serialisable, so two concurrent approvals cannot both observe the
    document as unapproved -- but the rule now lives in code rather than in the schema,
    which is a weaker place for it.
    """
    adj = db.collection(ADJ).document(_key(tenant_id, doc_id)).get()
    if not adj.exists or adj.to_dict().get("decision") != "escalate":
        seen = "no adjudication on record" if not adj.exists else adj.to_dict()["decision"]
        raise NotEscalated(f"{doc_id} was not escalated to a human ({seen})")

    ref = db.collection(APPROVALS).document(_key(tenant_id, doc_id))
    record = {
        "tenant_id": tenant_id, "doc_id": doc_id, "action": "approved",
        "approved_by": approved_by.strip().lower(),
        "codes": json.dumps(codes), "at": now(),
    }

    @firestore.transactional
    def _write(tx):
        snap = ref.get(transaction=tx)
        if snap.exists:
            existing = snap.to_dict()
            raise AlreadyApproved(
                f"{doc_id} was already approved by {existing['approved_by']} "
                f"at {existing['at']}")
        tx.set(ref, record)

    _write(db.transaction())
    _establish_trust(db, tenant_id, doc_id, record["approved_by"])
    return record


def _establish_trust(db, tenant_id: str, doc_id: str, approved_by: str) -> str | None:
    """Approval establishes trust here too. Same policy, different backend.

    Kept byte-for-byte equivalent in behaviour to store._establish_trust: if the two
    backends disagreed about what is trusted, the guarantee would depend on which one
    happened to be configured. tests/test_firestore_store.py pins them together.
    """
    doc = document(db, tenant_id, doc_id)
    if not doc or not doc.get("vendor_key"):
        return None

    acct = ""
    for f in findings_for(db, tenant_id, doc_id):
        if f.get("field") == "bank_account" and f.get("value"):
            acct = store.norm_account(f["value"])
            break
    if not acct:
        return None

    ref = db.collection(TRUSTED).document(f"{tenant_id}:{doc['vendor_key']}:{acct}")
    if ref.get().exists:
        return None
    ref.set({"tenant_id": tenant_id, "vendor_key": doc["vendor_key"],
             "bank_account": acct, "first_doc_id": doc_id,
             "approved_by": approved_by, "at": now()})
    return acct


def trusted_accounts(db, tenant_id: str, vendor_key: str) -> set[str]:
    """Accounts a human approved paying this vendor. The production trust boundary."""
    q = (db.collection(TRUSTED)
         .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
         .where(filter=firestore.FieldFilter("vendor_key", "==", vendor_key)))
    return {d.to_dict()["bank_account"] for d in q.stream()}


def trust_log(db, tenant_id: str | None = None) -> list[dict]:
    """Every trust decision, and who made it."""
    q = db.collection(TRUSTED)
    if tenant_id:
        q = q.where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
    return sorted((d.to_dict() for d in q.stream()),
                  key=lambda r: r["at"], reverse=True)


# ---------------------------------------------------------------- reads

def role_of(db, user_id: str, tenant_id: str) -> str | None:
    snap = db.collection(MEMBERS).document(
        f"{user_id.strip().lower()}:{tenant_id}").get()
    return snap.to_dict().get("role") if snap.exists else None


def password_hash_of(db, user_id: str) -> str | None:
    snap = db.collection(USERS).document(user_id.strip().lower()).get()
    return snap.to_dict().get("password_hash") if snap.exists else None


def tenants(db) -> list[dict]:
    return sorted((d.to_dict() for d in db.collection(TENANTS).stream()),
                  key=lambda t: t["id"])


def approvals(db, tenant_id: str | None = None) -> list[dict]:
    q = db.collection(APPROVALS)
    if tenant_id:
        q = q.where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
    return sorted((d.to_dict() for d in q.stream()),
                  key=lambda r: r["at"], reverse=True)


def purchase_order(db, tenant_id: str, po_ref: str) -> dict | None:
    snap = db.collection(POS).document(f"{tenant_id}:{po_ref.strip().upper()}").get()
    return snap.to_dict() if snap.exists else None


def document(db, tenant_id: str, doc_id: str) -> dict | None:
    snap = db.collection(DOCS).document(_key(tenant_id, doc_id)).get()
    return snap.to_dict() if snap.exists else None


def findings_for(db, tenant_id: str, doc_id: str) -> list[dict]:
    snap = db.collection(FINDINGS).document(_key(tenant_id, doc_id)).get()
    return snap.to_dict().get("rows", []) if snap.exists else []


def queue(db, tenant_id: str) -> list[dict]:
    """The review queue for one tenant, scoped by the same tenant_id filter throughout."""
    where = firestore.FieldFilter("tenant_id", "==", tenant_id)

    docs = {d.to_dict()["doc_id"]: d.to_dict()
            for d in db.collection(DOCS).where(filter=where).stream()}
    appr = {d.to_dict()["doc_id"]: d.to_dict()
            for d in db.collection(APPROVALS).where(filter=where).stream()}

    out = []
    for snap in db.collection(ADJ).where(filter=where).stream():
        a = snap.to_dict()
        doc = docs.get(a["doc_id"], {})
        approval = appr.get(a["doc_id"], {})
        out.append({
            "doc_id": a["doc_id"],
            "decision": a["decision"], "agent_decision": a["agent_decision"],
            "overridden": a.get("overridden"), "override_reason": a.get("override_reason"),
            "reason": a.get("reason"), "model": a.get("model"),
            "vendor_key": doc.get("vendor_key"), "doc_hash": doc.get("doc_hash"),
            "peer_invoices": doc.get("peer_invoices", 0),
            "source_path": doc.get("source_path"),
            "approved_by": approval.get("approved_by"),
            "approved_at": approval.get("at"),
            "findings": findings_for(db, tenant_id, a["doc_id"]),
        })
    return sorted(out, key=lambda r: r["doc_id"])


# ---------------------------------------------------------------- sessions

def add_session(db, token_hash: str, user_id: str, created_at: str, expires_at: str) -> None:
    db.collection(SESSIONS).document(token_hash).set({
        "token_hash": token_hash, "user_id": user_id,
        "created_at": created_at, "expires_at": expires_at})


def get_session(db, token_hash: str) -> dict | None:
    snap = db.collection(SESSIONS).document(token_hash).get()
    return snap.to_dict() if snap.exists else None


def delete_session(db, token_hash: str) -> None:
    db.collection(SESSIONS).document(token_hash).delete()


def delete_expired_sessions(db, cutoff: str) -> int:
    n = 0
    for snap in db.collection(SESSIONS).stream():
        row = snap.to_dict()
        if row.get("expires_at", "") <= cutoff:
            delete_session(db, row["token_hash"])
            n += 1
    return n
