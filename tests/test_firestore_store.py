"""The Firestore backend, tested against an in-memory fake.

There is no emulator here and no project credentials in CI, so the fake stands in for
Firestore's shape: documents addressed by collection and id, equality filters, and a
transaction that sees a consistent snapshot.

What these tests are really for is the one place the two backends genuinely differ.
SQLite enforces one-approval-per-document with `PRIMARY KEY (tenant_id, doc_id)`.
Firestore has no composite key, so the same rule lives in a transaction -- and a rule
that moved from the schema into code is exactly the kind of thing that quietly stops
being true. So it is pinned here as hard as it is pinned in tests/test_store.py.
"""
import pytest

from praetor import firestore_store as fs
from praetor.store import AlreadyApproved, NotEscalated

TENANT = "acme-industries"
OTHER = "borealis-retail"


# ---------------------------------------------------------------- the fake

class _Snap:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data else None


class _Doc:
    def __init__(self, store, coll, doc_id):
        self.store, self.coll, self.doc_id = store, coll, doc_id

    def set(self, data, merge=False):
        cur = self.store.setdefault(self.coll, {})
        if merge and self.doc_id in cur:
            cur[self.doc_id] = {**cur[self.doc_id], **data}
        else:
            cur[self.doc_id] = dict(data)

    def get(self, transaction=None):
        return _Snap(self.store.get(self.coll, {}).get(self.doc_id))


class _Query:
    def __init__(self, store, coll, field=None, value=None):
        self.store, self.coll, self.field, self.value = store, coll, field, value

    def where(self, filter=None):  # noqa: A002 - mirrors the real signature
        return _Query(self.store, self.coll, filter.field, filter.value)

    def stream(self):
        for data in self.store.get(self.coll, {}).values():
            if self.field is None or data.get(self.field) == self.value:
                yield _Snap(data)

    def document(self, doc_id):
        return _Doc(self.store, self.coll, doc_id)


class _Filter:
    def __init__(self, field, op, value):
        self.field, self.op, self.value = field, op, value


class _Tx:
    def __init__(self, store):
        self.store = store

    def set(self, ref, data):
        ref.set(data)


class FakeFirestore:
    def __init__(self):
        self.store: dict = {}

    def collection(self, name):
        return _Query(self.store, name)

    def transaction(self):
        return _Tx(self.store)


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    """Stand in for google.cloud.firestore without needing it installed or configured."""
    class _FS:
        FieldFilter = _Filter

        @staticmethod
        def transactional(fn):
            return fn

    monkeypatch.setattr(fs, "firestore", _FS, raising=False)
    monkeypatch.setattr(fs, "AVAILABLE", True, raising=False)


@pytest.fixture
def db():
    d = FakeFirestore()
    for t in (TENANT, OTHER):
        fs.add_tenant(d, t)
    fs.add_user(d, "approver@acme.test", "Approver")
    fs.grant(d, "approver@acme.test", TENANT, "approver")
    return d


def _escalated(d, tenant=TENANT, doc_id="D1"):
    fs.add_document(d, tenant, doc_id, "hash1", "meridian supply co", 13,
                    f"data/constructed/{doc_id}.json")
    fs.add_findings(d, tenant, doc_id,
                    [{"code": "BANK_UNKNOWN", "field": "bank_account",
                      "detail": "unseen account"}],
                    {"bank_account": {"value": "IN99-XXXX", "span_id": "p0:0.1",
                                      "tainted": True}})
    fs.add_adjudication(d, tenant, doc_id,
                        {"decision": "escalate", "agent_decision": "escalate"})
    return doc_id


# ---------------------------------------------------------------- approvals

def test_an_escalated_document_can_be_approved(db):
    doc = _escalated(db)
    row = fs.record_approval(db, TENANT, doc, "Approver@Acme.test", ["BANK_UNKNOWN"])
    assert row["approved_by"] == "approver@acme.test"


def test_approving_twice_is_refused(db):
    """The rule that moved out of the schema. It must still hold."""
    doc = _escalated(db)
    fs.record_approval(db, TENANT, doc, "approver@acme.test", [])
    with pytest.raises(AlreadyApproved):
        fs.record_approval(db, TENANT, doc, "someone@else.test", [])
    assert len(fs.approvals(db, TENANT)) == 1


def test_a_cleared_document_cannot_be_approved(db):
    fs.add_document(db, TENANT, "D2", "hash2")
    fs.add_adjudication(db, TENANT, "D2",
                        {"decision": "resolve", "agent_decision": "resolve"})
    with pytest.raises(NotEscalated):
        fs.record_approval(db, TENANT, "D2", "approver@acme.test", [])


def test_an_unknown_document_cannot_be_approved(db):
    with pytest.raises(NotEscalated):
        fs.record_approval(db, TENANT, "nope", "approver@acme.test", [])


# ---------------------------------------------------------------- tenancy

def test_the_queue_only_shows_one_tenants_documents(db):
    _escalated(db, TENANT, "A1")
    _escalated(db, OTHER, "B1")
    assert [r["doc_id"] for r in fs.queue(db, TENANT)] == ["A1"]
    assert [r["doc_id"] for r in fs.queue(db, OTHER)] == ["B1"]


def test_the_same_doc_id_in_two_tenants_stays_separate(db):
    _escalated(db, TENANT, "SHARED")
    _escalated(db, OTHER, "SHARED")
    fs.record_approval(db, TENANT, "SHARED", "approver@acme.test", [])
    assert len(fs.approvals(db, TENANT)) == 1
    assert fs.approvals(db, OTHER) == []


def test_a_document_is_only_visible_inside_its_tenant(db):
    _escalated(db, TENANT, "A1")
    assert fs.document(db, TENANT, "A1")["doc_id"] == "A1"
    assert fs.document(db, OTHER, "A1") is None


def test_roles_are_per_tenant(db):
    assert fs.role_of(db, "approver@acme.test", TENANT) == "approver"
    assert fs.role_of(db, "approver@acme.test", OTHER) is None


def test_an_invalid_role_is_refused(db):
    with pytest.raises(ValueError):
        fs.grant(db, "approver@acme.test", TENANT, "admin")


# ---------------------------------------------------------------- parity

def test_the_queue_carries_the_same_shape_as_sqlite(db):
    """Everything above the store is written against one shape. Both backends owe it."""
    _escalated(db)
    (row,) = fs.queue(db, TENANT)
    for key in ("doc_id", "decision", "agent_decision", "overridden", "override_reason",
                "reason", "model", "vendor_key", "doc_hash", "peer_invoices",
                "approved_by", "findings"):
        assert key in row, key


def test_findings_carry_provenance(db):
    _escalated(db)
    (f,) = fs.queue(db, TENANT)[0]["findings"]
    assert f["value"] == "IN99-XXXX"
    assert f["span_id"] == "p0:0.1"
    assert f["tainted"] is True
