"""Shared data contracts.

Kept deliberately small: the rules baseline and the agent path must consume the
*same* record type, or the comparison in eval/run_eval.py is not apples-to-apples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Provenance:
    """Where a value came from. Anything lifted off a document is tainted."""
    doc_hash: str
    span_id: str | None
    tainted: bool = True


@dataclass(frozen=True)
class Field:
    value: str
    prov: Provenance

    def __str__(self) -> str:
        return self.value


@dataclass
class InvoiceRecord:
    """One invoice, after extraction. Fields are optional: real documents omit things."""
    doc_id: str
    vendor_name: Field | None = None
    invoice_number: Field | None = None
    amount_total: Field | None = None
    currency: Field | None = None
    bank_account: Field | None = None
    tax_rate: Field | None = None
    vendor_address: Field | None = None
    line_item_count: int = 0

    def get(self, name: str) -> str | None:
        f = getattr(self, name, None)
        return f.value if isinstance(f, Field) else None


@dataclass
class VendorPattern:
    """What 'normal' looks like for one supplier, derived from their own past invoices.

    Nothing here is invented — every value is the mode or percentile of real
    documents in the corpus. See eval/build_vendor_master.py.
    """
    vendor_key: str
    n_invoices: int = 0
    bank_accounts: set[str] = field(default_factory=set)
    seen_invoice_numbers: set[str] = field(default_factory=set)
    modal_currency: str | None = None
    modal_tax_rate: str | None = None
    modal_address: str | None = None
    amount_p05: float | None = None
    amount_p95: float | None = None
    # fraction of this vendor's invoices that carry each field. A field is only
    # "expected" if this vendor usually provides it — so a corpus that simply has
    # no invoice numbers does not make every document an exception.
    field_presence: dict[str, float] = field(default_factory=dict)


class Verdict(str, Enum):
    PASS = "pass"            # no human needed
    EXCEPTION = "exception"  # needs a human decision


@dataclass(frozen=True)
class Finding:
    code: str      # stable machine code, e.g. BANK_UNKNOWN
    field: str
    detail: str


@dataclass
class Decision:
    doc_id: str
    verdict: Verdict
    findings: list[Finding] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]
