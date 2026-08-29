"""Smoke tests for the rules baseline.

These are not about accuracy — they prove the baseline behaves deterministically
so that eval/run_eval.py is comparing something real.
"""
from praetor.baseline_rules import evaluate
from praetor.types import Field, InvoiceRecord, Provenance, VendorPattern, Verdict

PROV = Provenance(doc_hash="deadbeef", span_id="S1", tainted=True)


def _f(v: str) -> Field:
    return Field(value=v, prov=PROV)


def _pattern() -> VendorPattern:
    return VendorPattern(
        vendor_key="meridian supply co",
        n_invoices=12,
        bank_accounts={"IN45-HDFC-0001-7788"},
        seen_invoice_numbers={"INV-2001"},
        modal_currency="USD",
        modal_tax_rate="18%",
        modal_address="14 Harbour Road, Rotterdam",
        amount_p05=1000.0,
        amount_p95=60000.0,
        field_presence={"vendor_name": 1.0, "invoice_number": 1.0,
                        "amount_total": 1.0, "bank_account": 1.0,
                        "vendor_address": 1.0},
    )


def _clean() -> InvoiceRecord:
    return InvoiceRecord(
        doc_id="doc-1",
        vendor_name=_f("Meridian Supply Co."),
        invoice_number=_f("INV-2291"),
        amount_total=_f("48,200.00"),
        currency=_f("USD"),
        bank_account=_f("IN45 HDFC 0001 7788"),   # same account, different spacing
        tax_rate=_f("18%"),
        vendor_address=_f("14 Harbour Road, Rotterdam"),
        line_item_count=4,
    )


def test_clean_invoice_passes():
    d = evaluate(_clean(), _pattern())
    assert d.verdict is Verdict.PASS, d.codes


def test_punctuation_in_account_is_not_an_exception():
    r = _clean()
    r.bank_account = _f("in45hdfc00017788")
    assert evaluate(r, _pattern()).verdict is Verdict.PASS


def test_changed_bank_account_is_flagged():
    r = _clean()
    r.bank_account = _f("IN99-XXXX-6666-0001")
    assert "BANK_UNKNOWN" in evaluate(r, _pattern()).codes


def test_unknown_vendor_is_an_exception():
    assert "UNKNOWN_VENDOR" in evaluate(_clean(), None).codes


def test_duplicate_invoice_number_is_flagged():
    r = _clean()
    r.invoice_number = _f("INV-2001")
    assert "DUPLICATE_INVOICE" in evaluate(r, _pattern()).codes


def test_amount_far_outside_history_is_flagged():
    r = _clean()
    r.amount_total = _f("980,000.00")
    assert "AMOUNT_OUT_OF_RANGE" in evaluate(r, _pattern()).codes


def test_missing_field_is_flagged_when_this_vendor_usually_has_it():
    r = _clean()
    r.invoice_number = None
    assert "MISSING_FIELD" in evaluate(r, _pattern()).codes


def test_missing_field_is_ignored_when_this_vendor_rarely_has_it():
    """A corpus without invoice numbers must not make every document an exception."""
    p = _pattern()
    p.field_presence["invoice_number"] = 0.05
    r = _clean()
    r.invoice_number = None
    assert "MISSING_FIELD" not in evaluate(r, p).codes


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")

# ------------------------------------------------- the invoice checked against itself

def _rec(total, lines):
    from praetor.types import Field, InvoiceRecord, Provenance
    r = InvoiceRecord(doc_id="d")
    prov = Provenance(doc_hash="h", span_id="s", tainted=True)
    if total is not None:
        r.amount_total = Field(value=total, prov=prov)
    r.line_item_amounts = [Field(value=v, prov=prov) for v in lines]
    return r


def test_lines_that_do_not_add_up_to_the_total_are_a_finding():
    """The one rule here that needs no supplier and no history: the invoice states a
    total and shows its working, and the two disagree.

    FINDINGS §28 measured the gap it closes -- an altered total was caught 1 time in 5
    and the reason was right 0 times, because there was no arithmetic in this system.
    """
    from praetor.baseline_rules import _line_items_sum

    f = _line_items_sum(_rec("1,000.00", ["100.00", "200.00", "300.00"]))
    assert f is not None and f.code == "LINE_ITEMS_DO_NOT_SUM"
    assert "600.00" in f.detail and "1,000.00" in f.detail


def test_lines_that_do_add_up_are_silent():
    from praetor.baseline_rules import _line_items_sum
    assert _line_items_sum(_rec("600.00", ["100.00", "200.00", "300.00"])) is None
    # rounding, and a total nudged inside the tolerance, must not fire
    assert _line_items_sum(_rec("600.01", ["100.00", "200.00", "300.00"])) is None


def test_an_unreadable_line_is_not_a_discrepancy():
    """A line we could not parse is a fact about our OCR, not about the invoice. Claiming
    a discrepancy there would fire on every scanned document -- which is exactly the
    class of false positive §29 found on real paper."""
    from praetor.baseline_rules import _line_items_sum
    assert _line_items_sum(_rec("600.00", ["100.00", "not a number", "300.00"])) is None


def test_it_needs_something_to_check():
    from praetor.baseline_rules import _line_items_sum
    assert _line_items_sum(_rec("600.00", [])) is None
    assert _line_items_sum(_rec("600.00", ["600.00"])) is None      # one line proves nothing
    assert _line_items_sum(_rec(None, ["100.00", "200.00"])) is None


def test_it_fires_without_a_vendor_pattern():
    """Every other rule in the file compares against the supplier's history and is silent
    on a first-time supplier. This one is not, and that is the point of it."""
    from praetor.baseline_rules import evaluate
    d = evaluate(_rec("1,000.00", ["100.00", "200.00"]), None)
    codes = {f.code for f in d.findings}
    assert "LINE_ITEMS_DO_NOT_SUM" in codes
    assert "UNKNOWN_VENDOR" in codes, "both facts should be reported, not just one"
