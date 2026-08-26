"""Per-tenant isolation, expressed as tests.

One AP processor runs many client companies. "An account we have seen from this
supplier" is only true inside one client's books, so a vendor master shared across
tenants would answer that question about the wrong company.

These tests are the reason the fleet cannot be merged into one agent with one shared
memory: doing so breaks an invariant that fails here.
"""
import pytest

from praetor.gate import Action, evaluate
from praetor.tenancy import CrossTenantError, VendorMaster
from praetor.types import Field, InvoiceRecord, Provenance, VendorPattern

VENDOR = "meridian supply co"
ACME_ACCOUNT = "IN45-HDFC-0001-7788"       # tenant "acme" pays Meridian here
BOREALIS_ACCOUNT = "IN45-HDFC-0009-2211"   # tenant "borealis" pays Meridian elsewhere


def _master() -> VendorMaster:
    m = VendorMaster()
    m.add("acme", VendorPattern(vendor_key=VENDOR, n_invoices=9,
                                bank_accounts={ACME_ACCOUNT}))
    m.add("borealis", VendorPattern(vendor_key=VENDOR, n_invoices=11,
                                    bank_accounts={BOREALIS_ACCOUNT}))
    return m


def _record(tenant: str, account: str) -> InvoiceRecord:
    return InvoiceRecord(
        doc_id="d1",
        tenant_id=tenant,
        vendor_name=Field("Meridian Supply Co.", Provenance("abc123", "p0:0.1", True)),
        bank_account=Field(account, Provenance("abc123", "p0:0.4", True)),
    )


# ---------------------------------------------------------------- the store

def test_each_tenant_sees_only_its_own_pattern():
    m = _master()
    assert m.pattern_for("acme", VENDOR).bank_accounts == {ACME_ACCOUNT}
    assert m.pattern_for("borealis", VENDOR).bank_accounts == {BOREALIS_ACCOUNT}


def test_a_miss_never_falls_back_to_another_tenant():
    """The bug this whole module exists to prevent."""
    m = _master()
    assert m.pattern_for("cinder", VENDOR) is None


def test_a_pattern_must_belong_to_a_tenant():
    with pytest.raises(ValueError):
        VendorMaster().add("", VendorPattern(vendor_key=VENDOR))


def test_adding_stamps_the_tenant_onto_the_pattern():
    m = _master()
    assert m.pattern_for("acme", VENDOR).tenant_id == "acme"


# ---------------------------------------------------------------- the gate

def test_an_account_known_to_another_tenant_does_not_satisfy_this_one():
    """Borealis's account is real — but not in Acme's books, so Acme must escalate."""
    m = _master()
    d = evaluate(_record("acme", BOREALIS_ACCOUNT), m.pattern_for("acme", VENDOR))
    assert d.action is Action.ESCALATE
    assert "TAINTED_ACCOUNT_NOT_IN_MASTER" in d.codes


def test_the_same_account_is_fine_in_its_own_tenant():
    m = _master()
    d = evaluate(_record("borealis", BOREALIS_ACCOUNT), m.pattern_for("borealis", VENDOR))
    assert d.action is Action.PROPOSE_PAY


def test_crossing_tenants_raises_rather_than_deciding():
    """Belt and braces: if a caller ever pairs them up wrongly, fail loudly."""
    m = _master()
    with pytest.raises(CrossTenantError):
        evaluate(_record("acme", ACME_ACCOUNT), m.pattern_for("borealis", VENDOR))


def test_merging_the_two_masters_would_break_the_guarantee():
    """Why the fleet stays split, as an assertion rather than a claim in a README.

    A single shared vendor master answers 'is this a known account for this supplier?'
    with yes for BOTH tenants' accounts. That is precisely the wrong answer, and it is
    what merging the agents would produce.
    """
    merged = VendorPattern(vendor_key=VENDOR, n_invoices=20,
                           bank_accounts={ACME_ACCOUNT, BOREALIS_ACCOUNT})
    leaked = evaluate(_record("acme", BOREALIS_ACCOUNT), merged)
    assert leaked.action is Action.PROPOSE_PAY   # the bug, demonstrated

    isolated = evaluate(_record("acme", BOREALIS_ACCOUNT),
                        _master().pattern_for("acme", VENDOR))
    assert isolated.action is Action.ESCALATE    # the fix
