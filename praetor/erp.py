"""The seam where a real ERP plugs in.

Every buyer-side fact this system trusts comes from somewhere: the accounts a supplier
has actually been paid at, the orders the buyer raised, the phone number to ring. Today
they come from JSON files a generator wrote. In a deployment they come from SAP, Oracle
Fusion, Dynamics or NetSuite.

This file is the boundary between those two worlds, and it exists so that the boundary is
one place rather than scattered through the code.

## The rule the seam enforces

**Everything reachable through here is a record the BUYER controls.** Nothing a supplier
sent may enter through this interface — not the invoice, not its text, not a value lifted
off it. That is not a naming convention, it is the trust boundary the whole architecture
rests on:

- [DECISIONS #5](../docs/DECISIONS.md) — the purchase-order register is written by the
  buyer, never scraped from documents, or a fabricated ticket would register itself and
  then validate the very thing the check exists to catch.
- [DECISIONS #12](../docs/DECISIONS.md) — trust is established by a person approving a
  payment, never by an invoice arriving.
- [DECISIONS #7](../docs/DECISIONS.md) — every lookup is scoped to one tenant, because
  "an account we have seen from this supplier" is only meaningful inside one client's
  books.

An adapter that answers these questions from the invoice being checked would defeat all
three at once, silently. `tests/test_erp.py` asserts the interface cannot carry a tainted
value, so a wrong adapter fails the build rather than the audit.

## Why a Protocol and not a base class

An ERP integration is somebody else's code, in somebody else's repository, on somebody
else's release cycle. A `Protocol` lets them satisfy this by shape without importing
PRAETOR or inheriting from it, and lets us type-check against it without ever running
their code.

`FileBackedERP` is the current behaviour, unchanged, expressed through the seam — so the
interface is proven by the thing already in use rather than by a mock.

Standard library only, no LLM. This is a data boundary, not a decision.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from praetor.types import VendorPattern

__all__ = ["ERP", "FileBackedERP", "PurchaseOrder", "SupplierContact", "UntrustedInput"]


class UntrustedInput(PermissionError):
    """Something off a document was passed to the seam. It is buyer-side records only."""


def _reject_tainted(value: object, what: str) -> None:
    """Refuse anything wearing document provenance.

    Duck-typed on the taint label that already exists, the same way
    `praetor/retrieval.py` does it, rather than inventing a second scheme to keep in
    step with the first.
    """
    for attr in ("prov", "origin"):
        prov = getattr(value, attr, None)
        if prov is not None and getattr(prov, "tainted", False):
            raise UntrustedInput(
                f"{what} came off a document. The ERP seam answers questions about what "
                f"the BUYER knows; a supplier's own invoice cannot be the source of the "
                f"record used to check it.")
    if getattr(value, "tainted", False):
        raise UntrustedInput(f"{what} came off a document.")


@dataclass(frozen=True)
class PurchaseOrder:
    """An order the buyer raised. The amount is what makes a citation checkable."""
    po_ref: str
    amount: float | None = None
    currency: str | None = None


@dataclass(frozen=True)
class SupplierContact:
    """How to reach a supplier, from the buyer's records.

    `source` is carried so a screen can say where the number came from. The standing
    instruction to an analyst is to ring the number in her own records and never the one
    printed on the invoice, and a contact with no provenance cannot support that.
    """
    name: str
    phone: str | None = None
    email: str | None = None
    contact_name: str | None = None
    source: str = "buyer records"


@runtime_checkable
class ERP(Protocol):
    """What PRAETOR needs from a system of record. Deliberately small.

    Four questions. An integration that answers these is complete; anything else it
    offers, PRAETOR does not want, because every additional answer is another thing that
    could be wrong in a direction that pays somebody.
    """

    def vendor_pattern(self, tenant_id: str, vendor_key: str) -> VendorPattern | None:
        """What normal looks like for this supplier, in THIS client's books."""

    def purchase_order(self, tenant_id: str, po_ref: str) -> PurchaseOrder | None:
        """An order the buyer raised, or None. Never derived from an invoice."""

    def supplier_contact(self, tenant_id: str, vendor_key: str) -> SupplierContact | None:
        """How to reach them, from the buyer's own records."""

    def tenants(self) -> Iterable[str]:
        """Which client companies this system of record covers."""


@dataclass
class FileBackedERP:
    """The current behaviour, expressed through the seam.

    Reads the JSON the generator writes. This is not a placeholder to be replaced so much
    as the reference implementation: it is what every measured number in `FINDINGS.md`
    was produced against, so an ERP adapter that disagrees with it is wrong.
    """

    root: Path
    tenant: str = "acme"

    def _load(self, name: str) -> dict:
        path = self.root / name
        return json.loads(path.read_text()) if path.exists() else {}

    # -- the interface

    def vendor_pattern(self, tenant_id: str, vendor_key: str) -> VendorPattern | None:
        _reject_tainted(vendor_key, "vendor_key")
        if tenant_id != self.tenant:
            return None                      # a miss is a miss; never another tenant's
        raw = self._load("vendor_master.json").get(str(vendor_key))
        if not raw:
            return None
        return VendorPattern(
            vendor_key=str(vendor_key), tenant_id=tenant_id,
            n_invoices=int(raw.get("n_invoices", 0)),
            bank_accounts=set(raw.get("bank_accounts") or []))

    def purchase_order(self, tenant_id: str, po_ref: str) -> PurchaseOrder | None:
        _reject_tainted(po_ref, "po_ref")
        if tenant_id != self.tenant:
            return None
        for row in self._load("po_register.json").get("purchase_orders", []):
            if str(row.get("po_ref", "")).upper() == str(po_ref).upper():
                return PurchaseOrder(po_ref=row["po_ref"], amount=row.get("amount"),
                                     currency=row.get("currency"))
        return None

    def supplier_contact(self, tenant_id: str, vendor_key: str) -> SupplierContact | None:
        _reject_tainted(vendor_key, "vendor_key")
        if tenant_id != self.tenant:
            return None
        raw = self._load("supplier_contacts.json").get(str(vendor_key).lower())
        if not raw:
            return None
        return SupplierContact(
            name=raw.get("name", ""), phone=raw.get("phone"), email=raw.get("email"),
            contact_name=raw.get("contact_name"),
            source=raw.get("source", "buyer records"))

    def tenants(self) -> Iterable[str]:
        return (self.tenant,)
