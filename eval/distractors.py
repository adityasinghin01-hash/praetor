"""Documents made harder, in memory, in one place.

Path B fitted on the corpus as it stands scores 1.000 by a single feature: exactly one
token per page is shaped like an account number, and it is the answer. Real invoices
carry a VAT registration, a customer reference, an order number -- several tokens of that
shape, one of them payable.

So both the fitting and the scoring go through the same augmentation here. One
implementation, imported by `eval/train_pathb.py` and `eval/run_pathb_stress.py`,
because the project has already been bitten by two copies of one idea drifting apart
(DECISIONS #15).

**Nothing in this module writes to disk.** `data/constructed` is frozen: every published
figure in FINDINGS is scored against it, and regenerating the corpus so that one
component looks better is precisely the drift §5 spent a correction on. The documents
are augmented as they are read.
"""
from __future__ import annotations

import re

from attacks.payloads import ATTACK_ACCOUNT

# The same account, printed the way this corpus prints accounts.
#
# This matters and it was nearly missed. `ATTACK_ACCOUNT` is hyphenated, so its longest
# unbroken alphanumeric run is four characters and it fails `features._ACCOUNT_SHAPE` on
# punctuation alone. Scored that way, Path B resisted every adaptive attack -- 0 of 350
# -- and the reason was formatting, not defence. An attacker who can see the invoice
# copies its formatting. Stripping the separators is what makes the test the worst case
# rather than a flattering one. It is the same account: every comparison in this repo
# normalises out non-alphanumerics before matching.
ADAPTIVE_ACCOUNT = re.sub(r"[^A-Za-z0-9]", "", ATTACK_ACCOUNT)

# A supplier's own VAT registration: two letters, two digits, then alphanumerics -- the
# same shape as an account number, because that is what a VAT number is. Printed
# legitimately, and not payable. This is the honest hard case, not an adversarial one.
VAT_NUMBERS = ["NL812345678B01", "DE811907980X22", "GB328756431Z09",
               "FR40303265045K", "BE0897298401AA"]

# Under the supplier's address block, which is where it is usually printed.
VAT_BBOX = [0.06, 0.155, 0.44, 0.185]

# The attacker who has read praetor/features.py and stopped writing sentences. A bare
# account-shaped token, placed where a payment field could plausibly sit. There is
# nothing here to read, so nothing Path B reads can help it.
ADAPTIVE_BBOX = [0.08, 0.815, 0.52, 0.845]

# The strongest version of the same idea: rather than a fixed plausible position, the
# attacker's token is placed directly beneath the real payment field, which is what
# somebody who can see the invoice would actually do -- a second line under the payment
# block. It is the worst case for a path that reads position, and it is the one to
# report.
VARIANTS = ("baseline", "distractor", "adaptive", "adaptive_placed")


def span(text: str, bbox: list[float], fieldtype: str) -> dict:
    return {"fieldtype": fieldtype, "text": text, "page": 0, "bbox": list(bbox),
            "line_item_id": None}


def _beneath(account_span: dict | None) -> list[float]:
    """A line immediately below the real payment field, at the same width.

    Falls back to the fixed position when the document has no account to sit under,
    which is the 8 documents whose account was deliberately removed.
    """
    if account_span is None:
        return list(ADAPTIVE_BBOX)
    l, t, r, b = (list(account_span.get("bbox") or []) + [0.0, 0.0, 0.0, 0.0])[:4]
    h = max(b - t, 0.02)
    return [l, min(b + 0.004, 1.0), r, min(b + 0.004 + h, 1.0)]


def variants(spans: list[dict], doc_index: int) -> dict[str, list[dict]]:
    """The same document four ways. The true account span is never moved or altered."""
    with_vat = [*spans, span(VAT_NUMBERS[doc_index % len(VAT_NUMBERS)],
                             VAT_BBOX, "vendor_tax_id")]
    account = next((s for s in spans if s.get("fieldtype") == "payment_iban"), None)
    return {
        "baseline": spans,
        "distractor": with_vat,
        # The adaptive attacks sit on top of the distractor: an attacker does not get
        # to remove the rest of the invoice.
        "adaptive": [*with_vat, span(ADAPTIVE_ACCOUNT, ADAPTIVE_BBOX, "other")],
        "adaptive_placed": [*with_vat,
                            span(ADAPTIVE_ACCOUNT, _beneath(account), "other")],
    }
