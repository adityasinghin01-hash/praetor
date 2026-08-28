"""The refusal network, and the one property that makes it safe to share.

DECISIONS #7 refuses to let one client's vendor master vouch for another's invoice.
This file shares information across that same boundary, so it needs an argument, and the
argument is an asymmetry: **a refusal can only ever raise a check.** If that is true, the
worst a hostile or careless tenant can do is cost somebody attention. If it is false,
cross-tenant sharing pays an attacker.

So it is not asserted once on a happy path. `test_the_network_can_only_ever_restrict`
walks every combination of prior findings, actions and network findings and checks the
result is never less restrictive than the input.
"""
from __future__ import annotations

import itertools

import pytest

from praetor.gate import Action, GateDecision, evaluate
from praetor.refusal import (REFUSED_ELSEWHERE, Refusal, RefusalNetwork, SaltRequired,
                             apply, fingerprint)
from praetor.types import Field, Finding, InvoiceRecord, Provenance, VendorPattern

SALT = "test-salt-not-a-default"
ATTACKER = "IN99-XXXX-6666-0001"
KNOWN = "IN45-HDFC-0001-7788"


def _record(tenant: str, account: str) -> InvoiceRecord:
    return InvoiceRecord(
        doc_id="d1", tenant_id=tenant,
        vendor_name=Field("Meridian Supply Co.", Provenance("h", "p0:0.1", True)),
        bank_account=Field(account, Provenance("h", "p0:0.4", True)))


# --------------------------------------------------------------- the safety property

def test_the_network_can_only_ever_restrict():
    """The property the whole design rests on, over every combination.

    A refusal may add a reason to look. It may never remove one, never loosen an action,
    and never carry an approval forward -- an approval riding through a shared warning
    would be exactly the cross-tenant payment path DECISIONS #7 forbids.
    """
    prior_findings = [
        [],
        [Finding("FIRST_TIME_VENDOR", "vendor_name", "x")],
        [Finding("TAINTED_ACCOUNT_NOT_IN_MASTER", "bank_account", "x"),
         Finding("AMOUNT_OUTSIDE_TOLERANCE", "amount_total", "x")],
    ]
    network_findings = [
        [],
        [Finding(REFUSED_ELSEWHERE, "bank_account", "refused at 1 other client")],
        [Finding(REFUSED_ELSEWHERE, "bank_account", "refused at 4 other clients")],
    ]
    for before, added, action, approver in itertools.product(
            prior_findings, network_findings, list(Action), [None, "priya"]):
        decision = GateDecision("d1", action, list(before), approved_by=approver)
        after = apply(decision, list(added))

        # 1. nothing is ever removed
        for f in before:
            assert f in after.findings, "the network removed a finding"
        # 2. the action never loosens
        if added:
            assert after.action is Action.ESCALATE
            # 3. an approval never survives a new warning
            assert after.approved_by is None
        else:
            assert after is decision, "an empty network must cost nothing"
        # 4. there is no route to APPROVED through this file
        if added:
            assert after.action is not Action.APPROVED


def test_it_never_satisfies_the_vendor_master():
    """The dangerous direction, checked directly.

    An account refused everywhere is still not *known* anywhere. The network has no way
    to make `TAINTED_ACCOUNT_NOT_IN_MASTER` go away, because it only ever appends.
    """
    net = RefusalNetwork(salt=SALT)
    net.record("borealis", ATTACKER)
    record = _record("acme", ATTACKER)
    pattern = VendorPattern(vendor_key="meridian supply co", tenant_id="acme",
                            n_invoices=9, bank_accounts={KNOWN})

    base = evaluate(record, pattern)
    after = apply(base, net.check(record, asking_tenant="acme"))

    assert "TAINTED_ACCOUNT_NOT_IN_MASTER" in after.codes
    assert REFUSED_ELSEWHERE in after.codes
    assert after.action is Action.ESCALATE


def test_a_clean_invoice_gains_a_check_and_never_loses_one():
    """The whole point: an account nobody here has refused, that somebody else did."""
    net = RefusalNetwork(salt=SALT)
    net.record("borealis", KNOWN)

    record = _record("acme", KNOWN)
    pattern = VendorPattern(vendor_key="meridian supply co", tenant_id="acme",
                            n_invoices=9, bank_accounts={KNOWN})
    base = evaluate(record, pattern)
    assert base.action is Action.PROPOSE_PAY, "premise: acme would have paid this"

    after = apply(base, net.check(record, asking_tenant="acme"))
    assert after.action is Action.ESCALATE
    assert after.codes == [REFUSED_ELSEWHERE]


# --------------------------------------------------------------- what crosses the line

def test_only_a_fingerprint_and_a_count_are_exposed():
    """Not the account, not which tenants, not the supplier."""
    net = RefusalNetwork(salt=SALT)
    net.record("borealis", ATTACKER)
    net.record("cinder", ATTACKER)
    found = net.lookup(ATTACKER)

    assert isinstance(found, Refusal)
    assert found.tenants == 2 and found.times == 2
    assert set(vars(found)) == {"fingerprint", "tenants", "times"}
    for value in vars(found).values():
        assert "IN99" not in str(value)
        assert "borealis" not in str(value) and "cinder" not in str(value)


def test_formatting_is_not_identity():
    for written in ("IN99-XXXX-6666-0001", "IN99 XXXX 6666 0001", "in99xxxx66660001"):
        assert fingerprint(written, SALT) == fingerprint("IN99XXXX66660001", SALT)


def test_a_different_salt_is_a_different_network():
    """Two operators must not be able to correlate each other's registries."""
    assert fingerprint(ATTACKER, "salt-a") != fingerprint(ATTACKER, "salt-b")


def test_a_network_without_a_salt_refuses_to_exist():
    """A default salt is a public salt, and a public salt makes the registry a list of
    account numbers somebody refused to pay."""
    with pytest.raises(SaltRequired):
        RefusalNetwork(salt="")
    with pytest.raises(SaltRequired):
        fingerprint(ATTACKER, "")


# --------------------------------------------------------------- who may write

def test_a_refusal_must_come_from_a_tenant():
    with pytest.raises(ValueError):
        RefusalNetwork(salt=SALT).record("", ATTACKER)


def test_a_tenant_is_not_warned_about_its_own_refusal():
    """Their own history is already theirs. What the network adds is what others found,
    and counting a tenant's own refusal as outside corroboration would inflate it."""
    net = RefusalNetwork(salt=SALT)
    net.record("acme", ATTACKER)
    assert net.check(_record("acme", ATTACKER), asking_tenant="acme") == []
    assert net.check(_record("borealis", ATTACKER), asking_tenant="borealis") != []


def test_distinct_tenants_are_counted_once_however_often_they_refuse():
    """Otherwise one client clicking twice outweighs two clients agreeing."""
    net = RefusalNetwork(salt=SALT)
    for _ in range(5):
        net.record("borealis", ATTACKER)
    found = net.lookup(ATTACKER)
    assert found.tenants == 1 and found.times == 5


def test_an_unknown_account_produces_nothing():
    net = RefusalNetwork(salt=SALT)
    assert net.lookup(KNOWN) is None
    assert net.check(_record("acme", KNOWN), asking_tenant="acme") == []


def test_a_record_with_no_account_has_nothing_to_check():
    net = RefusalNetwork(salt=SALT)
    net.record("borealis", ATTACKER)
    assert net.check(InvoiceRecord(doc_id="d", tenant_id="acme"), "acme") == []
