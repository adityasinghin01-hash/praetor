"""Every word Priya reads, in one file.

Priya is an AP analyst in Bengaluru processing ~300 invoices a day for a German client.
She has never heard of prompt injection and never will. Her fear is approving a
fraudulent payment and being blamed for it.

So the rule is absolute: **no code words on screen, ever.** If a term needs explaining,
it is the wrong term. `TAINTED` is not a thing she should have to learn; "this came off
the invoice" is a thing she already knows.

Three reasons this is one file rather than strings scattered through templates:

1. **Consistency.** The same finding must read identically in her queue, in her
   manager's report, and in the interactive demo. Three copies become three wordings.
2. **Auditability.** Someone should be able to read every sentence this product can say
   to a human, in one sitting, without reading any code around it.
3. **It gets checked.** `tests/test_language.py` asserts that every code the system can
   emit has an entry here, and that no entry contains a code word. A finding that
   reaches the screen untranslated fails the build rather than confusing Priya.

Each entry answers the two questions she actually has, in order:

    what is wrong   -- one sentence, no jargon, specific to this invoice
    what do I do    -- an instruction, not a description

Anything that is only meaningful to an engineer -- span ids, document hashes, the words
resolver, adjudicate, taint, gate -- is not translated. It is **hidden**.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Words that must never reach a screen. Checked by tests against every string we render.
#
# Matched on WORD BOUNDARIES, never as substrings. "Northgate Components Ltd" is a real
# supplier and must not trip a check for "gate"; a rule that cannot tell those apart
# gets switched off within a week, which is worse than not having it.
FORBIDDEN = ("tainted", "taint", "span_id", "doc_hash", "resolver", "adjudicate",
             "adjudication", "gate", "provenance", "injection", "payload", "prompt",
             "llm", "tenant_id", "escalate", "escalated", "privileged", "canary",
             "grounded", "heuristic", "classifier")

# What each field on the invoice is called, in words.
#
# The document view used to print the parser's own names -- `payment_iban`,
# `tax_detail_rate`, `currency_code_amount_due` -- straight onto the screen. That is
# exactly what this module exists to stop, and it slipped through because FORBIDDEN
# lists the machine's *concepts* and these are the machine's *field names*. Found by
# clicking "Show the invoice" and reading it.
FIELD_LABELS: dict[str, str] = {
    "vendor_name": "Supplier",
    "vendor_address": "Supplier address",
    "invoice_id": "Invoice number",
    "invoice_date": "Invoice date",
    "payment_iban": "Bank account",
    "payment_bank_account": "Bank account",
    "supplier_iban": "Bank account",
    "tax_detail_rate": "Tax rate",
    "currency_code_amount_due": "Currency",
    "amount_total": "Total",
    "total_amount": "Total",
    "line_item_description": "Item",
    "line_item_amount": "Item amount",
    "vendor_tax_id": "Supplier VAT number",
    "other": "Other text on the page",
    "__ambiguous__": "Text we could not place",
}


def field_label(fieldtype: str) -> str:
    """A person's name for one of the document's fields.

    An unknown field type is title-cased rather than hidden: a reviewer seeing a field
    we have no name for is better than a reviewer not seeing the field.
    """
    key = (fieldtype or "").strip()
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    return key.replace("_", " ").strip().capitalize() or "Unlabelled"


_WORD = re.compile(r"[a-z_]+")


def code_words_in(text: str) -> list[str]:
    """Which forbidden words appear in `text`, as whole words.

    One implementation, used by every test that enforces the language rule, so the rule
    cannot mean one thing in the phrasebook and something else in the API.
    """
    seen = set(_WORD.findall((text or "").lower()))
    return sorted(w for w in FORBIDDEN if w in seen)


# What happened to an invoice, as a person would say it. These are shown in the
# manager's view, so they cannot stay as the machine's own words.
OUTCOMES: dict[str, str] = {
    "escalated": "Waiting for someone to look",
    "override": "The system was overruled",
    "approved": "Approved by a person",
    "cleared": "Handled without a person",
}


def outcome_label(key: str) -> str:
    return OUTCOMES.get(key, "Waiting for someone to look")


@dataclass(frozen=True)
class Explanation:
    """What is wrong, and what to do about it. Both in Priya's words."""
    headline: str          # one line, shown in the queue row
    what_to_do: str        # an instruction
    severity: str = "check"   # "stop" | "check" -- drives ordering, not colour alone

    def as_dict(self) -> dict:
        return {"headline": self.headline, "what_to_do": self.what_to_do,
                "severity": self.severity}


# --------------------------------------------------------------------------- findings

EXPLANATIONS: dict[str, Explanation] = {
    # --- the ones that stop money
    "BANK_UNKNOWN": Explanation(
        "New bank account. You have never paid this supplier here before.",
        "Call the supplier on the number in your own records — not the number on this "
        "invoice — and ask them to confirm the account. Then use 'I called them'.",
        "stop"),
    "TAINTED_ACCOUNT_NOT_IN_MASTER": Explanation(
        "The bank account came off this invoice, and it does not match your records "
        "for this supplier.",
        "Call the supplier on the number in your own records and confirm the account "
        "before paying anything.",
        "stop"),
    "IMPOSSIBLE_ORIGIN": Explanation(
        "The bank account was printed in a note, not in the payment section. Real "
        "invoices do not do that.",
        "Treat this as suspicious. Call the supplier on the number in your own records. "
        "Do not use any contact details printed on this invoice.",
        "stop"),
    "ACCOUNT_REFUSED_ELSEWHERE": Explanation(
        "Someone at another company that uses this service refused to pay this same "
        "account.",
        "Treat this as a warning, not as proof. Call the supplier on the number in your "
        "own records — not the number on this invoice — and confirm the account before "
        "you pay it.",
        "stop"),
    "ORIGIN_UNKNOWN": Explanation(
        "We could not tell which part of the invoice the bank account was printed in.",
        "Open the invoice and check the account is in the payment section. If it is "
        "not, call the supplier on the number in your own records.",
        "stop"),

    # --- the ones that need a look
    "LINE_ITEMS_DO_NOT_SUM": Explanation(
        "The items on this invoice do not add up to the total it asks for.",
        "Add up the lines yourself and compare. If the total is higher than the items, "
        "ask the supplier for a corrected invoice before paying anything.",
        "check"),
    "AMOUNT_OUT_OF_RANGE": Explanation(
        "Much bigger than this supplier's normal invoice.",
        "Check there is a purchase order or an approval that covers this amount. If "
        "there is not, ask the person who ordered it.",
        "check"),
    "AMOUNT_OUTSIDE_TOLERANCE": Explanation(
        "The amount does not match the order it was raised against.",
        "Compare the invoice with the purchase order. If the difference is real, ask "
        "the person who ordered it to confirm before you approve.",
        "check"),
    "DUPLICATE_INVOICE": Explanation(
        "You may have already paid this one.",
        "Search your records for this invoice number. If it was already paid, reject "
        "this copy.",
        "check"),
    "CURRENCY_MISMATCH": Explanation(
        "Billed in a different currency than this supplier normally uses.",
        "Check the contract or purchase order for which currency was agreed.",
        "check"),
    "TAX_RATE_MISMATCH": Explanation(
        "The tax rate is not the one this supplier normally charges.",
        "Check whether an exemption or a different tax rule applies. If the invoice "
        "explains it, confirm the explanation is real before approving.",
        "check"),
    "ADDRESS_MISMATCH": Explanation(
        "The supplier's address is different from the one you have on file.",
        "Confirm the supplier has genuinely moved. A changed address alongside a "
        "changed bank account is a common sign of fraud.",
        "check"),
    "MISSING_FIELD": Explanation(
        "Something this supplier usually includes is missing from this invoice.",
        "Ask the supplier to send a complete invoice before you pay it.",
        "check"),
    "UNKNOWN_VENDOR": Explanation(
        "You have never paid this supplier before.",
        "Confirm the supplier is real and approved before the first payment. First "
        "payments are always worth a phone call.",
        "stop"),
    "FIRST_TIME_VENDOR": Explanation(
        "First time paying this supplier.",
        "Confirm the supplier is set up correctly, then approve. Every first payment "
        "gets checked by a person.",
        "stop"),
}

UNKNOWN = Explanation(
    "Something about this invoice does not match your records.",
    "Open the invoice and compare it with previous ones from this supplier.",
    "check")


def explain(code: str) -> Explanation:
    """Never raises. An unrecognised code gets a safe, honest sentence rather than a
    blank cell -- but `tests/test_language.py` fails if one exists, so it should not."""
    return EXPLANATIONS.get(code, UNKNOWN)


# ----------------------------------------------------------------------- the evidence

def evidence_note(code: str, seen: int, *, amount: str | None = None,
                  share: float | None = None) -> str | None:
    """The one line under a side-by-side comparison.

    Written to be exactly as strong as the data. The vendor master holds the *mode* of a
    supplier's past invoices, not a universal, so these say "usual" rather than "always" —
    a sentence that overstates what we checked is worse than no sentence, because the
    person acts on it.
    """
    if code == "BANK_UNKNOWN":
        if seen <= 0:
            return "You have no earlier invoices from this supplier to compare against."
        invoices = "invoice" if seen == 1 else "invoices"
        return (f"You have {seen} earlier {invoices} from this supplier, "
                f"and none of them used this account.")

    if code == "DUPLICATE_INVOICE":
        if amount:
            return f"The invoice on the right is already in your records, for {amount}."
        return "This invoice number is already in your records."

    if code == "CURRENCY_MISMATCH":
        return f"Their usual currency across {seen} earlier invoices."

    if code == "TAX_RATE_MISMATCH":
        return f"Their usual rate across {seen} earlier invoices."

    if code == "ADDRESS_MISMATCH":
        return f"The address on their earlier invoices, {seen} of them."

    if code == "AMOUNT_OUT_OF_RANGE":
        return f"What this supplier usually charges, across {seen} earlier invoices."

    if code == "MISSING_FIELD":
        if share is None:
            return "This supplier normally fills this in."
        return f"This supplier fills this in on {share * 100:.0f}% of their invoices."

    return None


# ------------------------------------------------------------------- writing to them

#: Three things a person writes on an invoice again and again. Problem 10: she should not
#: have to type any of them. Kept here because they are words a person reads, and this is
#: the one file that is audited for those.
CANNED_NOTES = (
    "I called them on the number in our records and they confirmed it.",
    "I could not reach them. Trying again tomorrow.",
    "Emailed them to confirm. Waiting for a reply.",
)


def draft_email(code: str, supplier: str, field: str | None = None) -> dict | None:
    """The email she would otherwise write by hand.

    Problem 6 asks for the missing field to be named *and the email drafted*; problem 11
    says the phone call cannot be automated, so writing instead is the part that can be.
    Both are the same feature and this is it.

    The wording deliberately does not quote the invoice back at them beyond the field
    name. An email that repeats an attacker's text is an email that carries it onward.
    """
    who = supplier or "there"
    if code == "MISSING_FIELD":
        missing = field or "a field we need"
        return {
            "subject": f"{supplier}: one field missing on your invoice",
            "body": (f"Hello {who},\n\n"
                     f"We have your invoice but cannot process it yet — {missing.lower()} "
                     f"is not on it.\n\n"
                     f"Could you send that, or a corrected invoice?\n\n"
                     f"Thank you."),
        }
    if code in ("BANK_UNKNOWN", "ACCOUNT_REFUSED_ELSEWHERE", "TAINTED_ACCOUNT_NOT_IN_MASTER"):
        return {
            "subject": f"{supplier}: confirming your bank details",
            "body": (f"Hello {who},\n\n"
                     f"Your latest invoice gives an account we have not paid before. "
                     f"Before we pay it, could you confirm the account by phone on the "
                     f"number we already hold for you?\n\n"
                     f"We will not act on bank details sent by email alone.\n\n"
                     f"Thank you."),
        }
    return None


# ------------------------------------------------------------------------- the outcome

def outcome_sentence(decision: str, overridden: bool, override_reason: str | None,
                     ) -> str:
    """What the system did, said the way she would say it to her manager."""
    if not overridden:
        if decision == "resolve":
            return "We checked this one and it was fine. No action needed."
        return "This needs a person to decide."

    # The interesting case: the AI wanted to wave it through and was refused.
    why = {
        "privileged field": "the account it wants to pay is not one you have used "
                            "before, and nothing written on an invoice can approve that",
        "no pre-authorised rule holds for this exception":
            "nothing in your own records backs up the explanation on the invoice",
    }.get((override_reason or "").strip())
    if why is None and (override_reason or "").startswith("unverified authority"):
        why = ("the invoice says it was approved, and we checked — there is no such "
               "approval in your records")
    if why is None:
        why = "your own records did not back up the explanation on the invoice"
    return f"The system read this and thought it was fine. We disagreed, because {why}."


# ----------------------------------------------------------------- the interactive demo

STEP_NAMES: dict[str, str] = {
    "spans": "Read the invoice",
    "reference": "Check the answer points at the document",
    "origin": "Check the account came from the payment section",
    "master": "Check the account against your own supplier records",
    "authority": "Check any approval the invoice claims for itself",
    "rules": "Compare with this supplier's previous invoices",
    "human": "Decide whether a person must look",
}


def step_name(key: str) -> str:
    return STEP_NAMES.get(key, key.replace("_", " ").capitalize())
