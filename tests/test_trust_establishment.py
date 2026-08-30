"""Where trust comes from, and the attack that exists when it comes from the wrong place.

The vendor master answers one question: "have we paid this supplier at this account
before?" Everything in the gate rests on that answer, so it matters enormously *how the
answer gets written*.

`eval/build_vendor_master.py` derives it from a directory of documents. That is correct
for MEASURING a detection rule -- you want to know whether a deviation from the modal
pattern is caught -- and it is wrong as a trust boundary, because the documents come
from outside the company. An attacker who can send invoices can write to it.

test_arrival_alone_poisons_the_master demonstrates that directly. The fix is that trust
is established by approval and by nothing else, which is what the rest of this file
pins. See docs/DECISIONS.md #12.
"""
from __future__ import annotations

import pytest

from praetor import store

TENANT = "acme-industries"
VENDOR = "meridian supply co"
REAL_ACCOUNT = "NL78RABO5699252753"
ATTACKER_ACCOUNT = "IN99-XXXX-6666-0001"


@pytest.fixture()
def conn(tmp_path):
    c = store.connect(tmp_path / "trust.db")
    store.add_tenant(c, TENANT, "Acme Industries")
    store.add_user(c, "reviewer@acme.test")
    store.grant(c, "reviewer@acme.test", TENANT, "approver")
    return c


def _arrive(c, doc_id: str, account: str, *, escalate: bool = True) -> None:
    """An invoice arrives and is processed. Nobody has approved anything yet."""
    store.add_document(c, TENANT, doc_id, doc_hash=f"hash-{doc_id}", vendor_key=VENDOR)
    store.add_findings(c, TENANT, doc_id,
                       [{"code": "BANK_UNKNOWN", "field": "bank_account",
                         "detail": "account not seen before"}],
                       evidence={"bank_account": {"value": account,
                                                  "span_id": "p0:0.1_0.7_0.5_0.8",
                                                  "tainted": True}})
    store.add_adjudication(c, TENANT, doc_id, {
        "decision": "escalate" if escalate else "resolve",
        "agent_decision": "escalate", "overridden": False,
        "override_reason": None, "reason": "unknown account", "model": "test"})


# --------------------------------------------------------------- the attack

def test_arrival_alone_poisons_the_master():
    """The bug, demonstrated: derive trust from arrivals and the attacker writes to it.

    This is the naive construction -- "every account we have seen on an invoice from
    this vendor" -- which is what a master built by globbing a document directory gives
    you. The attacker needs no approval and no compromise. They send two invoices.
    """
    seen_accounts: set[str] = set()

    def naive_master_sees(account: str) -> bool:
        known = store.norm_account(account) in seen_accounts
        seen_accounts.add(store.norm_account(account))   # arrival writes to the store
        return known

    # A genuine invoice establishes the real account.
    assert naive_master_sees(REAL_ACCOUNT) is False

    # Invoice 1 from the attacker. Unknown, so it escalates -- but it has now been seen.
    assert naive_master_sees(ATTACKER_ACCOUNT) is False

    # Invoice 2. Same account. The naive master now vouches for it.
    assert naive_master_sees(ATTACKER_ACCOUNT) is True, (
        "expected the naive arrival-derived master to be poisoned by the first invoice")


def test_approval_gated_master_is_not_poisoned_by_arrivals(conn):
    """The fix. Two attacker invoices arrive, nobody approves, nothing becomes trusted."""
    _arrive(conn, "ATK_001", ATTACKER_ACCOUNT)
    _arrive(conn, "ATK_002", ATTACKER_ACCOUNT)

    assert store.trusted_accounts(conn, TENANT, VENDOR) == set(), (
        "arrival must never establish trust")


# ------------------------------------------------------- approval establishes trust

def test_approval_is_what_establishes_trust(conn):
    _arrive(conn, "INV_001", REAL_ACCOUNT)
    assert store.trusted_accounts(conn, TENANT, VENDOR) == set()

    store.record_approval(conn, TENANT, "INV_001", "reviewer@acme.test", ["BANK_UNKNOWN"])

    assert store.trusted_accounts(conn, TENANT, VENDOR) == {
        store.norm_account(REAL_ACCOUNT)}


def test_trust_is_scoped_to_the_vendor_that_earned_it(conn):
    """An account approved for one supplier says nothing about another."""
    _arrive(conn, "INV_001", REAL_ACCOUNT)
    store.record_approval(conn, TENANT, "INV_001", "reviewer@acme.test", ["BANK_UNKNOWN"])

    assert store.trusted_accounts(conn, TENANT, "some other supplier ltd") == set()


def test_trust_is_scoped_to_the_tenant_that_earned_it(conn):
    """The tenancy guarantee, restated at the trust boundary rather than the lookup."""
    store.add_tenant(conn, "beta-corp", "Beta Corp")
    _arrive(conn, "INV_001", REAL_ACCOUNT)
    store.record_approval(conn, TENANT, "INV_001", "reviewer@acme.test", ["BANK_UNKNOWN"])

    assert store.trusted_accounts(conn, "beta-corp", VENDOR) == set(), (
        "one client's approval must never vouch for another client's invoice")


def test_formatting_is_not_identity(conn):
    """The same account written differently is the same account."""
    _arrive(conn, "INV_001", "NL78 RABO 5699 2527 53")
    store.record_approval(conn, TENANT, "INV_001", "reviewer@acme.test", ["BANK_UNKNOWN"])

    assert store.norm_account("nl78-rabo-5699-252753") in store.trusted_accounts(
        conn, TENANT, VENDOR)


# ------------------------------------------------------------------ the audit trail

def test_every_trusted_account_names_who_trusted_it(conn):
    """An auditor's first question is 'who decided this account was safe?'"""
    _arrive(conn, "INV_001", REAL_ACCOUNT)
    store.record_approval(conn, TENANT, "INV_001", "reviewer@acme.test", ["BANK_UNKNOWN"])

    log = store.trust_log(conn, TENANT)
    assert len(log) == 1
    assert log[0]["approved_by"] == "reviewer@acme.test"
    assert log[0]["first_doc_id"] == "INV_001"
    assert log[0]["at"]


def test_an_agent_can_never_establish_trust(conn):
    """gate.approve refuses agent identities, so the trust path is closed to them too.

    This is the same invariant as 'no input to the gate produces APPROVED', restated
    where it now also matters: an agent that could approve could also mint trust.
    """
    from praetor.gate import Action, GateDecision, approve

    _arrive(conn, "INV_001", ATTACKER_ACCOUNT)
    decision = GateDecision("INV_001", Action.ESCALATE, [])

    with pytest.raises(PermissionError):
        approve(decision, "agent:exception_resolver")

    assert store.trusted_accounts(conn, TENANT, VENDOR) == set()


def test_a_document_with_no_account_trusts_nothing(conn):
    """Approving an invoice that carries no account must not create an empty trust row."""
    store.add_document(conn, TENANT, "INV_002", doc_hash="h2", vendor_key=VENDOR)
    store.add_findings(conn, TENANT, "INV_002",
                       [{"code": "MISSING_FIELD", "field": "bank_account",
                         "detail": "absent"}])
    store.add_adjudication(conn, TENANT, "INV_002", {
        "decision": "escalate", "agent_decision": "escalate", "overridden": False,
        "override_reason": None, "reason": "no account", "model": "test"})

    store.record_approval(conn, TENANT, "INV_002", "reviewer@acme.test", ["MISSING_FIELD"])

    assert store.trusted_accounts(conn, TENANT, VENDOR) == set()


# ------------------------------------------------------- rejection establishes nothing

def test_rejecting_never_establishes_trust(conn):
    """The asymmetry the whole feature rests on.

    Key `2` on screen 04 is Fraud. It writes to the same table as an approval and inherits
    the same duplicate guard, which is why it reuses `action` rather than getting a table
    of its own -- but routing it through `_establish_trust` would mark the attacker's
    account as known-good on the strength of a person saying it was fraudulent. That is
    the precise inversion this test exists to prevent.
    """
    _arrive(conn, "INV_001", ATTACKER_ACCOUNT)

    store.record_decision(conn, TENANT, "INV_001", "reviewer@acme.test",
                          ["BANK_UNKNOWN"], "rejected")

    assert store.trusted_accounts(conn, TENANT, VENDOR) == set(), (
        "a rejection must never vouch for the account it rejected")
    assert store.trust_log(conn, TENANT) == []


def test_a_rejected_invoice_cannot_then_be_approved(conn):
    """Deciding is once. Flagging fraud must not leave the door open to paying it."""
    _arrive(conn, "INV_001", ATTACKER_ACCOUNT)
    store.record_decision(conn, TENANT, "INV_001", "reviewer@acme.test", [], "rejected")

    with pytest.raises(store.AlreadyApproved):
        store.record_approval(conn, TENANT, "INV_001", "reviewer@acme.test", [])

    assert store.trusted_accounts(conn, TENANT, VENDOR) == set()


def test_a_decision_must_be_one_of_the_two(conn):
    _arrive(conn, "INV_001", REAL_ACCOUNT)
    with pytest.raises(ValueError):
        store.record_decision(conn, TENANT, "INV_001", "reviewer@acme.test", [], "paid")
