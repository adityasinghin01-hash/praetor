"""Adjudicates flagged exceptions: can this be resolved, or does a human decide?

Why this exists: the rules baseline already catches every deviation we plant —
recall 1.000, F1 0.865 (see FINDINGS.md). Detection is a solved problem here.
What rules cannot do is read the note on the invoice saying *"includes annual
licence true-up per contract MSA-2024-118"* and conclude that the amount is fine.

So this agent does not detect. It adjudicates. Every exception it resolves
correctly is one a person never has to look at.

It sees structured findings and context spans — never the raw document. And its
answer is advisory: `adjudicate()` applies the gate afterwards, so on privileged
fields the outcome is ESCALATE no matter what the agent concluded. A convincing
remittance notice printed on an untrusted invoice is exactly the attack, and the
guarantee cannot depend on the agent not falling for it.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from praetor.agents.reader import MODEL_CHAIN, _api_key

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

Answer with ONLY this JSON:
{{"decision": "resolve" | "escalate", "reason": "<one short sentence>"}}
"""


@dataclass
class Adjudication:
    decision: str          # final, after the gate
    agent_decision: str    # what the agent wanted
    reason: str
    overridden: bool       # did the gate override the agent?
    model: str | None = None


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


def adjudicate(findings, pattern, context: list[str], client=None,
               models=MODEL_CHAIN) -> Adjudication:
    """Ask the agent, then let the gate have the last word."""
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
        from google import genai
        client = genai.Client(api_key=_api_key())

    prompt = PROMPT.format(findings=finding_txt, pattern=pattern_txt, context=context_txt)

    agent_decision, reason, used = "escalate", "model unavailable", None
    for model in models:
        delay = 6.0
        for _ in range(3):
            try:
                r = client.models.generate_content(model=model, contents=prompt)
                agent_decision, reason = _parse(r.text or "")
                used = model
                break
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
    if used is None:
        # Every model unavailable. Failing closed is the only safe default here:
        # an unreachable adjudicator must never silently resolve an exception.
        return Adjudication("escalate", "escalate", "no model available", False, None)

    # The gate has the last word. This is the guarantee: it does not depend on the
    # agent resisting a persuasive note.
    if privileged and agent_decision == "resolve":
        return Adjudication("escalate", agent_decision, reason, True, used)
    return Adjudication(agent_decision, agent_decision, reason, False, used)
