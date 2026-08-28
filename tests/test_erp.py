"""The ERP seam, and the one rule it exists to enforce.

Every buyer-side fact this system trusts comes through here: the accounts a supplier has
actually been paid at, the orders the buyer raised, the number to ring. In a deployment
those come from SAP or Oracle rather than from JSON files.

The rule is that **nothing a supplier sent may enter through this interface.** An adapter
that answered these questions from the invoice being checked would defeat DECISIONS #5,
#7 and #12 at once, silently, and the system would keep working while meaning nothing.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from praetor.erp import (ERP, FileBackedERP, PurchaseOrder, SupplierContact,
                         UntrustedInput)
from praetor.types import Field, Provenance

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAINTED = Provenance(doc_hash="abc", span_id="p0:0.1_0.2_0.3_0.4", tainted=True)


@pytest.fixture
def erp(tmp_path):
    (tmp_path / "vendor_master.json").write_text(json.dumps({
        "meridian supply co": {"n_invoices": 9, "bank_accounts": ["NL12RABO0001"]}}))
    (tmp_path / "po_register.json").write_text(json.dumps({
        "purchase_orders": [{"po_ref": "PO-68910", "amount": 12400.0, "currency": "EUR"}]}))
    (tmp_path / "supplier_contacts.json").write_text(json.dumps({
        "meridian supply co": {"name": "Meridian Supply Co.", "phone": "+31 20 555 1234",
                               "source": "buyer records"}}))
    return FileBackedERP(root=tmp_path, tenant="acme")


# --------------------------------------------------------------- the rule

@pytest.mark.parametrize("method", ["vendor_pattern", "purchase_order", "supplier_contact"])
def test_a_value_off_a_document_cannot_enter_the_seam(erp, method):
    """The failure this file exists to prevent, on every entry point.

    A supplier's own invoice cannot be the source of the record used to check it.
    """
    tainted = Field("meridian supply co", TAINTED)
    with pytest.raises(UntrustedInput):
        getattr(erp, method)("acme", tainted)


def test_the_refusal_names_the_reason_rather_than_the_value(erp):
    """An error message that echoes the input is a message that leaks it into a log."""
    with pytest.raises(UntrustedInput) as excinfo:
        erp.purchase_order("acme", Field("PO-SECRET-8891", TAINTED))
    assert "PO-SECRET-8891" not in str(excinfo.value)
    assert "BUYER" in str(excinfo.value)


# --------------------------------------------------------------- tenant scoping

@pytest.mark.parametrize("method,argument", [
    ("vendor_pattern", "meridian supply co"),
    ("purchase_order", "PO-68910"),
    ("supplier_contact", "meridian supply co"),
])
def test_every_lookup_is_scoped_to_one_tenant(erp, method, argument):
    """DECISIONS #7. A miss is a miss -- it never falls back to another client's books."""
    assert getattr(erp, method)("acme", argument) is not None
    assert getattr(erp, method)("borealis", argument) is None


# --------------------------------------------------------------- the interface

def test_the_file_backed_adapter_satisfies_the_protocol():
    """The reference implementation is the thing already in use, so the interface is
    proven by real behaviour rather than by a mock written to fit it."""
    assert isinstance(FileBackedERP(root=ROOT / "data"), ERP)


def test_the_seam_stays_small():
    """Four questions. Every additional answer an integration offers is another thing
    that could be wrong in a direction that pays somebody."""
    methods = {m for m in dir(ERP) if not m.startswith("_")}
    assert methods == {"vendor_pattern", "purchase_order", "supplier_contact", "tenants"}


def test_it_returns_what_the_buyer_knows(erp):
    pattern = erp.vendor_pattern("acme", "meridian supply co")
    assert pattern.bank_accounts == {"NL12RABO0001"}
    assert pattern.tenant_id == "acme"

    assert erp.purchase_order("acme", "PO-68910") == PurchaseOrder(
        po_ref="PO-68910", amount=12400.0, currency="EUR")

    contact = erp.supplier_contact("acme", "meridian supply co")
    assert isinstance(contact, SupplierContact)
    assert contact.phone == "+31 20 555 1234"
    assert contact.source == "buyer records"


def test_a_purchase_order_reference_is_matched_without_case(erp):
    assert erp.purchase_order("acme", "po-68910") is not None


def test_a_missing_record_is_none_rather_than_an_invention(erp):
    assert erp.vendor_pattern("acme", "nobody ltd") is None
    assert erp.purchase_order("acme", "PO-00000") is None
    assert erp.supplier_contact("acme", "nobody ltd") is None


def test_the_kernel_does_not_import_the_seam_yet():
    """Honest status: the seam is defined and the adapter works, but the kernel still
    reads its files directly. Wiring it through is a change to code every measured
    number depends on, so it is a separate, deliberate step -- and this test records
    that it has not happened rather than letting the docs imply it has.
    """
    import ast

    offenders = []
    for path in sorted((ROOT / "praetor").rglob("*.py")):
        if path.name == "erp.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("erp"):
                offenders.append(path.name)
    assert offenders == [], (
        f"{offenders} now import the ERP seam. That is the intended direction -- update "
        f"this test and FINDINGS when it happens deliberately.")
