"""The database.

Everything used to live in append-only JSON Lines under out/. That was fine for an
experiment and wrong for a product, for two reasons that both bite at the same place:
an append is not a transaction, so two approvals racing can interleave; and a file has
no uniqueness constraint, so the same invoice could be approved twice and the log would
faithfully record both.

The approvals table fixes the second one structurally: its primary key is
(tenant_id, doc_id), so a duplicate approval is a constraint violation rather than a
second row. Idempotency is a property of the schema, not of remembering to check.

Tenancy is in the schema for the same reason. Every table that holds anything about a
document carries tenant_id, and every read is scoped by it, so a cross-tenant leak has
to get past the query planner rather than past a code review.

JSONL stays as the export format -- results/ still holds the published measurements and
`make demo` still works from files alone. The database is where live state lives; the
files are where evidence lives.

No LLM in this file.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "out" / "praetor.db"

# The corpus is one client company's books. Naming it makes the single-tenant
# assumption visible instead of implicit.
DEFAULT_TENANT = "acme-industries"

ROLES = ("approver", "viewer")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,        -- canonical email
    name          TEXT,
    password_hash TEXT,
    created_at    TEXT NOT NULL
);

-- Only the hash of a session token is stored, so a copy of this database does not
-- hand over live sessions.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS memberships (
    user_id     TEXT NOT NULL REFERENCES users(id),
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    role        TEXT NOT NULL CHECK (role IN ('approver', 'viewer')),
    PRIMARY KEY (user_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS documents (
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    doc_id       TEXT NOT NULL,
    doc_hash     TEXT NOT NULL,
    vendor_key   TEXT,
    peer_invoices INTEGER DEFAULT 0,
    ingested_at  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, doc_id)
);

CREATE TABLE IF NOT EXISTS findings (
    tenant_id  TEXT NOT NULL,
    doc_id     TEXT NOT NULL,
    code       TEXT NOT NULL,
    field      TEXT NOT NULL,
    detail     TEXT,
    value      TEXT,
    span_id    TEXT,
    tainted    INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tenant_id, doc_id) REFERENCES documents(tenant_id, doc_id)
);
CREATE INDEX IF NOT EXISTS findings_doc ON findings(tenant_id, doc_id);

CREATE TABLE IF NOT EXISTS adjudications (
    tenant_id       TEXT NOT NULL,
    doc_id          TEXT NOT NULL,
    decision        TEXT NOT NULL,
    agent_decision  TEXT NOT NULL,
    overridden      INTEGER NOT NULL DEFAULT 0,
    override_reason TEXT,
    reason          TEXT,
    model           TEXT,
    at              TEXT NOT NULL,
    PRIMARY KEY (tenant_id, doc_id),
    FOREIGN KEY (tenant_id, doc_id) REFERENCES documents(tenant_id, doc_id)
);

-- One approval per document per tenant. A second attempt is a constraint violation,
-- which is what makes approving idempotent without anyone having to remember.
CREATE TABLE IF NOT EXISTS approvals (
    tenant_id    TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    action       TEXT NOT NULL,
    approved_by  TEXT NOT NULL REFERENCES users(id),
    codes        TEXT,
    at           TEXT NOT NULL,
    PRIMARY KEY (tenant_id, doc_id),
    FOREIGN KEY (tenant_id, doc_id) REFERENCES documents(tenant_id, doc_id)
);

-- The buyer's own purchase orders: the trusted record praetor/authority.py checks
-- document-claimed approvals against, and the amounts the policy gate reconciles to.
CREATE TABLE IF NOT EXISTS purchase_orders (
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    po_ref     TEXT NOT NULL,
    amount     REAL,
    currency   TEXT,
    PRIMARY KEY (tenant_id, po_ref)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Columns added after the first schema shipped. CREATE TABLE IF NOT EXISTS will not
# add a column to a table that already exists, so every later addition needs a line here
# and the database stays upgradable instead of needing to be thrown away.
MIGRATIONS = [
    ("documents", "peer_invoices", "ALTER TABLE documents ADD COLUMN peer_invoices INTEGER DEFAULT 0"),
    ("users", "password_hash", "ALTER TABLE users ADD COLUMN password_hash TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ddl in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(ddl)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """One transaction. Either all of it lands or none of it does."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------- writes

def add_tenant(conn, tenant_id: str, name: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO tenants(id, name, created_at) VALUES (?,?,?)",
                 (tenant_id, name or tenant_id, now()))


def add_user(conn, user_id: str, name: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO users(id, name, created_at) VALUES (?,?,?)",
                 (user_id.strip().lower(), name, now()))


def grant(conn, user_id: str, tenant_id: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    conn.execute(
        "INSERT INTO memberships(user_id, tenant_id, role) VALUES (?,?,?) "
        "ON CONFLICT(user_id, tenant_id) DO UPDATE SET role = excluded.role",
        (user_id.strip().lower(), tenant_id, role))


def add_document(conn, tenant_id, doc_id, doc_hash, vendor_key=None,
                 peer_invoices=0) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO documents"
        "(tenant_id, doc_id, doc_hash, vendor_key, peer_invoices, ingested_at)"
        " VALUES (?,?,?,?,?,?)",
        (tenant_id, doc_id, doc_hash, vendor_key, int(peer_invoices or 0), now()))


def add_findings(conn, tenant_id, doc_id, findings, evidence=None) -> None:
    evidence = evidence or {}
    conn.execute("DELETE FROM findings WHERE tenant_id=? AND doc_id=?", (tenant_id, doc_id))
    for f in findings:
        ev = evidence.get(f["field"], {})
        conn.execute(
            "INSERT INTO findings(tenant_id, doc_id, code, field, detail, value, span_id, tainted)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (tenant_id, doc_id, f["code"], f["field"], f.get("detail"),
             ev.get("value"), ev.get("span_id"), int(ev.get("tainted", True))))


def add_adjudication(conn, tenant_id, doc_id, row) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO adjudications"
        "(tenant_id, doc_id, decision, agent_decision, overridden, override_reason,"
        " reason, model, at) VALUES (?,?,?,?,?,?,?,?,?)",
        (tenant_id, doc_id, row["decision"], row.get("agent_decision", row["decision"]),
         int(bool(row.get("overridden"))), row.get("override_reason"),
         row.get("reason"), row.get("model"), now()))


def add_purchase_order(conn, tenant_id, po_ref, amount=None, currency=None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO purchase_orders(tenant_id, po_ref, amount, currency)"
        " VALUES (?,?,?,?)",
        (tenant_id, po_ref.strip().upper(), amount, currency))


class AlreadyApproved(RuntimeError):
    """This document already has an approval. Approving is idempotent by schema."""


class NotEscalated(RuntimeError):
    """Only a document a human was actually asked to decide can be approved."""


def record_approval(conn, tenant_id, doc_id, approved_by, codes) -> dict:
    """Write the approval, refusing a duplicate or a document nobody escalated.

    Both refusals matter. The first stops a double payment; the second stops an approval
    being manufactured for an invoice that was never put in front of a person.
    """
    row = conn.execute(
        "SELECT decision FROM adjudications WHERE tenant_id=? AND doc_id=?",
        (tenant_id, doc_id)).fetchone()
    if row is None or row["decision"] != "escalate":
        seen = "no adjudication on record" if row is None else row["decision"]
        raise NotEscalated(f"{doc_id} was not escalated to a human ({seen})")

    try:
        with tx(conn):
            conn.execute(
                "INSERT INTO approvals(tenant_id, doc_id, action, approved_by, codes, at)"
                " VALUES (?,?,?,?,?,?)",
                (tenant_id, doc_id, "approved", approved_by.strip().lower(),
                 json.dumps(codes), now()))
    except sqlite3.IntegrityError as e:
        existing = conn.execute(
            "SELECT approved_by, at FROM approvals WHERE tenant_id=? AND doc_id=?",
            (tenant_id, doc_id)).fetchone()
        if existing:
            raise AlreadyApproved(
                f"{doc_id} was already approved by {existing['approved_by']} "
                f"at {existing['at']}") from e
        raise

    return dict(conn.execute(
        "SELECT * FROM approvals WHERE tenant_id=? AND doc_id=?",
        (tenant_id, doc_id)).fetchone())


# ---------------------------------------------------------------- reads

def role_of(conn, user_id: str, tenant_id: str) -> str | None:
    row = conn.execute(
        "SELECT role FROM memberships WHERE user_id=? AND tenant_id=?",
        (user_id.strip().lower(), tenant_id)).fetchone()
    return row["role"] if row else None


def tenants(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM tenants ORDER BY id")]


def approvals(conn, tenant_id: str | None = None) -> list[dict]:
    if tenant_id:
        rows = conn.execute("SELECT * FROM approvals WHERE tenant_id=? ORDER BY at DESC",
                            (tenant_id,))
    else:
        rows = conn.execute("SELECT * FROM approvals ORDER BY at DESC")
    return [dict(r) for r in rows]


def purchase_order(conn, tenant_id: str, po_ref: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE tenant_id=? AND po_ref=?",
        (tenant_id, po_ref.strip().upper())).fetchone()
    return dict(row) if row else None


def queue(conn, tenant_id: str) -> list[dict]:
    """The review queue for one tenant: adjudicated documents with their evidence."""
    rows = conn.execute(
        "SELECT a.doc_id, a.decision, a.agent_decision, a.overridden, a.override_reason,"
        "       a.reason, a.model, d.vendor_key, d.doc_hash, d.peer_invoices,"
        "       ap.approved_by, ap.at AS approved_at"
        "  FROM adjudications a"
        "  JOIN documents d ON d.tenant_id = a.tenant_id AND d.doc_id = a.doc_id"
        "  LEFT JOIN approvals ap ON ap.tenant_id = a.tenant_id AND ap.doc_id = a.doc_id"
        " WHERE a.tenant_id = ?"
        " ORDER BY a.doc_id", (tenant_id,)).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d["findings"] = [dict(f) for f in conn.execute(
            "SELECT code, field, detail, value, span_id, tainted"
            "  FROM findings WHERE tenant_id=? AND doc_id=?", (tenant_id, r["doc_id"]))]
        out.append(d)
    return out
