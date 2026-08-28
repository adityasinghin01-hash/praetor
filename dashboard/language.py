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
    "ORIGIN_UNKNOWN": Explanation(
        "We could not tell which part of the invoice the bank account was printed in.",
        "Open the invoice and check the account is in the payment section. If it is "
        "not, call the supplier on the number in your own records.",
        "stop"),

    # --- the ones that need a look
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
