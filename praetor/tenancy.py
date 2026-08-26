"""Per-tenant isolation of the vendor master.

PRAETOR's target user is an outsourced AP processor: one company running accounts
payable for many client companies at once. That is not a deployment detail — it is the
thing that forces the fleet to stay split, because "known supplier bank account" is only
meaningful inside one client's books.

The failure this prevents is specific and expensive. Tenant A and tenant B both buy from
"Meridian Supply Co.", and the two of them hold different accounts for it. If the vendor
master is a flat dictionary keyed on supplier name, tenant A's account silently satisfies
tenant B's invoice, and the gate's central check — *is this account one we have seen from
this supplier?* — answers yes about the wrong company's supplier.

So the lookup is scoped, and the scope is not advisory: `pattern_for` cannot return
another tenant's pattern because it never looks outside the tenant's own bucket, and
`gate.evaluate` raises `CrossTenantError` if a record and a pattern from different
tenants are ever put in front of it. Two independent mechanisms, because this one is
worth failing loudly over.

No LLM in this file, by design.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from praetor.types import VendorPattern


class CrossTenantError(PermissionError):
    """A pattern from one tenant was put in front of another tenant's invoice."""


@dataclass
class VendorMaster:
    """Vendor patterns, bucketed by tenant. There is no global bucket, deliberately."""

    _by_tenant: dict[str, dict[str, VendorPattern]] = field(default_factory=dict)

    @property
    def tenants(self) -> list[str]:
        return sorted(self._by_tenant)

    def add(self, tenant_id: str, pattern: VendorPattern) -> None:
        if not tenant_id:
            raise ValueError("a vendor pattern must belong to a tenant")
        stamped = VendorPattern(**{**pattern.__dict__, "tenant_id": tenant_id})
        self._by_tenant.setdefault(tenant_id, {})[pattern.vendor_key] = stamped

    def pattern_for(self, tenant_id: str, vendor_key: str) -> VendorPattern | None:
        """The only way in. A miss is a miss — it never falls back to another tenant."""
        return self._by_tenant.get(tenant_id, {}).get(vendor_key)

    def vendor_keys(self, tenant_id: str) -> list[str]:
        return sorted(self._by_tenant.get(tenant_id, {}))

    @classmethod
    def load(cls, path: str | Path, tenant_id: str) -> VendorMaster:
        """Load a single-tenant vendor master file into a tenant's bucket.

        The existing eval pipeline writes one file per corpus, which is one tenant's
        books. Loading it under an explicit tenant id is what turns an implicit
        single-tenant assumption into a stated one.
        """
        raw = json.loads(Path(path).read_text())
        master = cls()
        for vendor_key, rows in raw.items():
            accounts = {r.get("bank_account") for r in rows if r.get("bank_account")}
            master.add(tenant_id, VendorPattern(
                vendor_key=vendor_key,
                n_invoices=len(rows),
                bank_accounts={a for a in accounts if a},
            ))
        return master
