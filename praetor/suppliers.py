"""Contact details for suppliers, from the buyer's own records.

This looks like a convenience feature and is not one. It is the same decision as
`DECISIONS.md` #5, applied to a phone number.

When an invoice arrives with a changed bank account, the correct thing to do is ring the
supplier and ask. Every AP team knows this. The failure mode is that the analyst rings
**the number printed on the invoice** — which, if the invoice is fraudulent, is the
attacker's number, and they will happily confirm the account. The call feels like
diligence and is the opposite of it. This is the single most common way invoice fraud
gets past a careful person.

So the number Priya sees must come from a record the buyer controls, and the screen must
say where it came from. A contact register scraped from previous invoices would fail the
same way one supplier-supplied document at a time.

**The invariant, and it is enforced by a test:** nothing in this module may read a
document. `load()` takes a path to a buyer-side file and nothing else. There is no
function here that accepts an invoice, an annotation, or a span.

Standard library only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "supplier_contacts.json"


@dataclass(frozen=True)
class Contact:
    """What the buyer knows about how to reach a supplier, independent of any invoice."""
    vendor_key: str
    name: str
    phone: str
    email: str
    contact_name: str | None = None
    source: str = "buyer records"       # shown on screen, always
    verified_on: str | None = None      # when the buyer last confirmed these details

    def as_dict(self) -> dict:
        return {"vendor_key": self.vendor_key, "name": self.name, "phone": self.phone,
                "email": self.email, "contact_name": self.contact_name,
                "source": self.source, "verified_on": self.verified_on}


@lru_cache(maxsize=4)
def load(path: str | Path | None = None) -> dict[str, Contact]:
    """The buyer's contact register, keyed by vendor key.

    A missing register is not an error: the queue still works, it just cannot offer a
    number, and the screen says so rather than falling back to the invoice.
    """
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    out: dict[str, Contact] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        out[key] = Contact(
            vendor_key=key,
            name=str(entry.get("name", key)),
            phone=str(entry.get("phone", "")),
            email=str(entry.get("email", "")),
            contact_name=entry.get("contact_name"),
            source=str(entry.get("source", "buyer records")),
            verified_on=entry.get("verified_on"),
        )
    return out


def for_vendor(vendor_key: str, path: str | Path | None = None) -> Contact | None:
    """The buyer's own contact record for one supplier, or None if there isn't one.

    Returning None is the honest answer and the safe one. The caller must show "no
    number on file — find one through your own systems", never a number off the invoice.
    """
    if not vendor_key:
        return None
    return load(path).get(vendor_key.strip().lower())
