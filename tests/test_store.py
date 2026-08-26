"""The database, expressed as tests.

Two properties matter more than the rest, and both are enforced by the schema rather
than by anyone remembering to check:

  * a document can be approved at most once  (primary key on tenant_id, doc_id);
  * only a document a human was actually asked to decide can be approved at all.

The tenant tests are the same isolation invariant as tests/test_tenancy.py, one layer
down: there, a pattern cannot vouch for another tenant's invoice; here, a query cannot
see another tenant's rows.
"""
import pytest

from praetor import store

TENANT = "acme-industries"
OTHER = "borealis-retail"


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "t.db")
    with store.tx(c):
        for t in (TENANT, OTHER):
            store.add_tenant(c, t)
        store.add_user(c, "approver@acme.test", "Approver")
        store.add_user(c, "viewer@acme.test", "Viewer")
        store.grant(c, "approver@acme.test", TENANT, "approver")
        store.grant(c, "viewer@acme.test", TENANT, "viewer")
    return c


def _escalated(c, tenant=TENANT, doc_id="D1"):
    with store.tx(c):
        store.add_document(c, tenant, doc_id, "hash1", "meridian supply co")
        store.add_findings(c, tenant, doc_id,
                           [{"code": "BANK_UNKNOWN", "field": "bank_account",
                             "detail": "unseen account"}],
                           {"bank_account": {"value": "IN99-XXXX", "span_id": "p0:0.1",
                                             "doc_hash": "hash1", "tainted": True}})
        store.add_adjudication(c, tenant, doc_id,
                               {"decision": "escalate", "agent_decision": "escalate"})
    return doc_id


# ---------------------------------------------------------------- approvals

def test_an_escalated_document_can_be_approved(conn):
    doc = _escalated(conn)
    row = store.record_approval(conn, TENANT, doc, "approver@acme.test", ["BANK_UNKNOWN"])
    assert row["approved_by"] == "approver@acme.test"
    assert row["action"] == "approved"


def test_approving_twice_is_refused(conn):
    """A double approval is a double payment. The schema makes it impossible."""
    doc = _escalated(conn)
    store.record_approval(conn, TENANT, doc, "approver@acme.test", [])
    with pytest.raises(store.AlreadyApproved):
        store.record_approval(conn, TENANT, doc, "someone@else.test", [])
    assert len(store.approvals(conn, TENANT)) == 1


def test_a_cleared_document_cannot_be_approved(conn):
    """Approval only means something for a decision a person was actually handed."""
    with store.tx(conn):
        store.add_document(conn, TENANT, "D2", "hash2")
        store.add_adjudication(conn, TENANT, "D2",
                               {"decision": "resolve", "agent_decision": "resolve"})
    with pytest.raises(store.NotEscalated):
        store.record_approval(conn, TENANT, "D2", "approver@acme.test", [])


def test_an_unknown_document_cannot_be_approved(conn):
    with pytest.raises(store.NotEscalated):
        store.record_approval(conn, TENANT, "nope", "approver@acme.test", [])


# ---------------------------------------------------------------- roles

def test_roles_are_per_tenant(conn):
    assert store.role_of(conn, "approver@acme.test", TENANT) == "approver"
    assert store.role_of(conn, "approver@acme.test", OTHER) is None


def test_an_unknown_user_has_no_role(conn):
    assert store.role_of(conn, "stranger@nowhere.test", TENANT) is None


def test_a_grant_can_be_changed_not_duplicated(conn):
    with store.tx(conn):
        store.grant(conn, "viewer@acme.test", TENANT, "approver")
    assert store.role_of(conn, "viewer@acme.test", TENANT) == "approver"
    n = conn.execute("SELECT COUNT(*) c FROM memberships WHERE user_id=?",
                     ("viewer@acme.test",)).fetchone()["c"]
    assert n == 1


def test_an_invalid_role_is_refused(conn):
    with pytest.raises(ValueError):
        store.grant(conn, "viewer@acme.test", TENANT, "admin")


# ---------------------------------------------------------------- tenant isolation

def test_the_queue_only_shows_one_tenants_documents(conn):
    _escalated(conn, TENANT, "A1")
    _escalated(conn, OTHER, "B1")
    assert [r["doc_id"] for r in store.queue(conn, TENANT)] == ["A1"]
    assert [r["doc_id"] for r in store.queue(conn, OTHER)] == ["B1"]


def test_the_same_doc_id_in_two_tenants_stays_separate(conn):
    """Two clients of one AP processor can legitimately use the same invoice numbering."""
    _escalated(conn, TENANT, "SHARED")
    _escalated(conn, OTHER, "SHARED")
    store.record_approval(conn, TENANT, "SHARED", "approver@acme.test", [])
    assert len(store.approvals(conn, TENANT)) == 1
    assert store.approvals(conn, OTHER) == []


def test_approvals_are_scoped_by_tenant(conn):
    _escalated(conn, TENANT, "A1")
    _escalated(conn, OTHER, "B1")
    store.record_approval(conn, TENANT, "A1", "approver@acme.test", [])
    assert [a["doc_id"] for a in store.approvals(conn, TENANT)] == ["A1"]
    assert store.approvals(conn, OTHER) == []


# ---------------------------------------------------------------- purchase orders

def test_purchase_orders_carry_amounts_and_are_scoped(conn):
    with store.tx(conn):
        store.add_purchase_order(conn, TENANT, "po-68910", 4120.00, "EUR")
    po = store.purchase_order(conn, TENANT, "PO-68910")
    assert po["amount"] == 4120.00
    assert store.purchase_order(conn, OTHER, "PO-68910") is None


def test_findings_carry_provenance(conn):
    doc = _escalated(conn)
    (f,) = store.queue(conn, TENANT)[0]["findings"]
    assert f["value"] == "IN99-XXXX"
    assert f["span_id"] == "p0:0.1"
    assert f["tainted"] == 1


# ---------------------------------------------------------------- document lookup

def test_a_document_is_only_visible_inside_its_tenant(conn):
    """What the viewer endpoint relies on: another client's document simply is not there."""
    _escalated(conn, TENANT, "A1")
    assert store.document(conn, TENANT, "A1")["doc_id"] == "A1"
    assert store.document(conn, OTHER, "A1") is None


def test_findings_are_only_visible_inside_their_tenant(conn):
    _escalated(conn, TENANT, "A1")
    assert len(store.findings_for(conn, TENANT, "A1")) == 1
    assert store.findings_for(conn, OTHER, "A1") == []


def test_a_document_records_where_it_came_from(conn):
    with store.tx(conn):
        store.add_document(conn, TENANT, "D9", "hash9",
                           source_path="data/constructed/D9.json")
    assert store.document(conn, TENANT, "D9")["source_path"] == "data/constructed/D9.json"


def test_an_unknown_document_is_none_not_an_error(conn):
    assert store.document(conn, TENANT, "does-not-exist") is None
