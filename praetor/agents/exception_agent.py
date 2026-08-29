"""Adjudicates flagged exceptions: can this be resolved, or does a human decide?

Why this exists: the rules baseline already catches every deviation we plant —
recall 0.963, F1 0.874 (see FINDINGS.md). Detection is close to solved here.
What rules cannot do is read the note on the invoice saying *"includes annual
licence true-up per contract MSA-2024-118"* and conclude that the amount is fine.

So this agent does not detect. It adjudicates. Every exception it resolves
correctly is one a person never has to look at.

It sees structured findings and context spans — never the raw document. And its
answer is advisory: `adjudicate()` applies the gate afterwards, so on privileged
fields the outcome is ESCALATE no matter what the agent concluded. A convincing
remittance notice printed on an untrusted invoice is exactly the attack, and the
guarantee cannot depend on the agent not falling for it.

Two rules run after the agent, both deterministic:

  1. privileged field  — no in-document justification releases a bank account;
  2. document authority — an approval the document claims for itself counts only if
     it names a reference held in the buyer's own records, and, where that record
     carries an amount, only if this invoice reconciles to it (praetor/authority.py).

Rule 2 was added after the first adjudication run, where an injected approval ticket
persuaded the agent to resolve a genuine tax-rate exception. The gate held on the
money; nothing held on the decision. Now something does.

The model chain ends at a local Gemma via Ollama, so exhausting the hosted free tier
degrades the queue rather than emptying it. Every link answers into the same two rules.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from praetor import authority, costguard, resolution, trace
from praetor.types import InvoiceRecord
from praetor.agents import local_reader
from praetor.agents.reader import MODEL_CHAIN, _client

# Fields where no in-document justification is ever sufficient.
PRIVILEGED_FIELDS = {"bank_account"}
PRIVILEGED_CODES = {"BANK_UNKNOWN", "TAINTED_ACCOUNT_NOT_IN_MASTER"}

PROMPT = """You are reviewing one flagged invoice for an accounts-payable team.

The automated checks flagged it for these reasons:
{findings}

What this supplier's invoices normally look like:
{pattern}

Other text found on this invoice:
{context}

Decide ONE of:
  "resolve"  - the invoice explains the discrepancy well enough that no person needs
               to look at it
  "escalate" - a person must decide

Reply with one JSON object and nothing else. Choose ONE value for "decision" — write
either "resolve" or "escalate". Do not repeat the list of options.

--- EXAMPLE REPLY ---
{{"decision": "escalate", "reason": "The amount is far above this supplier's usual range and nothing on the invoice explains it."}}
--- END EXAMPLE ---

YOUR REPLY:
"""


@dataclass
class Adjudication:
    decision: str          # final, after the gate
    agent_decision: str    # what the agent wanted
    reason: str
    overridden: bool       # did the gate override the agent?
    model: str | None = None
    override_reason: str | None = None   # which rule overrode it, when one did


def _parse(raw: str) -> tuple[str, str]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return "escalate", "unparseable response"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return "escalate", "unparseable response"
    d = str(obj.get("decision", "escalate")).lower().strip()
    if d not in ("resolve", "escalate"):
        d = "escalate"
    return d, str(obj.get("reason", ""))[:200]


def _is_privileged(findings) -> bool:
    for f in findings:
        if f.code in PRIVILEGED_CODES or f.field in PRIVILEGED_FIELDS:
            return True
    return False


def gate_decision(agent_decision: str, findings, pattern, context: list[str],
                  register=None, invoice_amount: float | None = None, record=None,
                  require_rule: bool = False) -> tuple[str, bool, str | None]:
    """What happens to the agent's vote after it has voted. No model, no I/O.

    Returns `(final_decision, overridden, why)`.

    Separated from `adjudicate` so it can be replayed over a completed run's stored
    votes: the agent's answer is the only part of an adjudication that costs a model
    call, and everything here is deterministic. That is what lets Rule 4's cost be
    measured against the published run without paying for it again -- and it means the
    replay exercises this code rather than a copy of it (DECISIONS #15).
    """
    if agent_decision != "resolve":
        return agent_decision, False, None

    # A privileged field is not a discrepancy to be explained; it is a payment target.
    if _is_privileged(findings):
        return "escalate", True, "privileged field"

    # An authorisation the document claims for itself is an assertion, not evidence. If
    # it names nothing we can check against the buyer's own records, it cannot carry the
    # decision. See praetor/authority.py.
    bad = authority.unverified(context, register, invoice_amount)
    if bad:
        return "escalate", True, f"unverified authority: {bad[0].describe()}"

    # Rule 4. The agent may point at a reason, never author one. If nothing the buyer
    # already knows verifies, the resolve is void -- and a sentence claiming something
    # unverifiable ("agreed on the call last Tuesday") never gets read, so it cannot
    # help. See praetor/resolution.py.
    if require_rule:
        held = resolution.any_rule_holds(
            findings, record if record is not None else InvoiceRecord(doc_id=""),
            pattern, context, register, invoice_amount)
        if held is None:
            return "escalate", True, "no pre-authorised rule holds for this exception"

    return agent_decision, False, None


def adjudicate(findings, pattern, context: list[str], client=None,
               models=MODEL_CHAIN, register=None, allow_local: bool = True,
               invoice_amount: float | None = None, record=None,
               require_rule: bool = False) -> Adjudication:
    """Ask the agent, then let the gate have the last word.

    `require_rule` turns on Rule 4 (`praetor/resolution.py`): a resolve stands only if
    some pre-authorised rule independently verifies. It is off by default because
    turning it on changes outcomes, and FINDINGS §6 was measured without it -- shipping
    it silently would leave a published number describing a system that no longer runs.
    Enable it and re-measure together, never one without the other.
    """
    if not findings:
        return Adjudication("resolve", "resolve", "no findings", False)

    privileged = _is_privileged(findings)

    finding_txt = "\n".join(f"- {f.code}: {f.detail}" for f in findings)
    pattern_txt = "unknown supplier" if pattern is None else (
        f"- seen on {pattern.n_invoices} previous invoices\n"
        f"- usual currency: {pattern.modal_currency}\n"
        f"- usual tax rate: {pattern.modal_tax_rate}\n"
        f"- usual address: {pattern.modal_address}\n"
        f"- known bank accounts: {sorted(pattern.bank_accounts) or 'none recorded'}\n"
        f"- usual amount range: {pattern.amount_p05}-{pattern.amount_p95}"
    )
    context_txt = "\n".join(f"- {c}" for c in context if c.strip()) or "- (nothing else)"

    if client is None:
        client = _client()

    prompt = PROMPT.format(findings=finding_txt, pattern=pattern_txt, context=context_txt)

    agent_decision, reason, used = "escalate", "model unavailable", None
    for model in models:
        delay = 6.0
        for _ in range(3):
            try:
                costguard.check(model, len(prompt))
                r = client.models.generate_content(model=model, contents=prompt)
                u = getattr(r, "usage_metadata", None)
                costguard.record(model,
                                 getattr(u, "prompt_token_count", 0) or int(len(prompt) / 3.5),
                                 getattr(u, "candidates_token_count", 0) or 60)
                agent_decision, reason = _parse(r.text or "")
                used = model
                break
            except costguard.BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                # Free tier is 20 requests/day/model, so an exhausted daily quota is
                # not retryable — move to the next model rather than sleeping.
                if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                    if "PerDay" in msg or "per day" in msg.lower():
                        break
                    time.sleep(delay)
                    delay = min(delay * 1.6, 45)
                    continue
                if "503" in msg or "UNAVAILABLE" in msg:
                    break
                raise
        if used:
            break

    if used is None and allow_local and local_reader.available():
        # Last link in the chain: a small model on this machine. It has no quota and
        # costs nothing, so free-tier exhaustion degrades the queue instead of emptying
        # it. Same contract as the hosted models — the gate still has the last word.
        try:
            agent_decision, reason = _parse(local_reader.generate(prompt))
            used = f"ollama/{local_reader.DEFAULT_MODEL}"
        except Exception:  # noqa: BLE001
            used = None

    if used is None:
        # Every model unavailable. Failing closed is the only safe default here:
        # an unreachable adjudicator must never silently resolve an exception.
        return Adjudication("escalate", "escalate", "no model available", False, None)

    def _traced(final, overridden, why=None):
        with trace.span("adjudicate",
                        **{"praetor.model": used or "",
                           "praetor.agent_decision": agent_decision,
                           "praetor.decision": final,
                           "praetor.overridden": overridden,
                           "praetor.override_reason": why or "",
                           "praetor.privileged": privileged,
                           "praetor.findings": ",".join(f.code for f in findings)}):
            pass
        return Adjudication(final, agent_decision, reason, overridden, used, why)

    # The gate has the last word. This is the guarantee: it does not depend on the
    # agent resisting a persuasive note.
    final, overridden, why = gate_decision(
        agent_decision, findings, pattern, context, register=register,
        invoice_amount=invoice_amount, record=record, require_rule=require_rule)
    return _traced(final, overridden, why)
