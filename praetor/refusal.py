"""The refusal network: a warning may cross a tenant boundary, a permission may never.

[DECISIONS #7](../docs/DECISIONS.md) forbids one client's vendor master from vouching for
another's invoice, and gives up cross-client intelligence to get it. apexanalytix ships
exactly that intelligence as a feature. This file is how PRAETOR takes back the half of
it that is safe to have.

The asymmetry is the whole idea, and it is not a matter of degree:

    sharing "this account is trusted"   lets one client's mistake pay another
                                        client's attacker.  Never.
    sharing "a person refused to pay    can, at worst, cause a second person to
    this account"                       look at an invoice.  Always allowed.

A refusal can only ever *raise a check*. There is no input to this file, and no state it
can reach, that causes a payment, clears a finding, or moves a gate decision from
escalate to propose. `apply()` returns the findings it was given plus zero or more new
ones, and `tests/test_refusal.py` asserts over generated combinations that the result is
never less restrictive than the input.

That is what makes this safe to share across a boundary the rest of the system refuses
to cross.

## What actually crosses, and what does not

Only a **fingerprint** — a salted SHA-256 of the normalised account — and a count of how
many distinct tenants refused it. Not the account. Not which tenants. Not the supplier,
the amount, or the document.

The fingerprint is not privacy theatre. A tenant checking an invoice already holds the
account printed on it, so hashing costs them nothing; what it stops is the registry
itself being a list of account numbers that somebody refused to pay, which is
commercially sensitive about the *supplier* and useful to an attacker deciding which
account to reuse. Without the salt the registry cannot be enumerated, only queried by
someone who already has a candidate.

**The salt is required.** There is no default, because a default salt is a public salt.

## Who may write to it

Only a person refusing to pay. Not the gate escalating, not the agent, not ingestion.

This mirrors [DECISIONS #12](../docs/DECISIONS.md) exactly: trust is established by
approval and never by arrival, so refusal is established by a person's refusal and never
by the system merely being suspicious. If escalations wrote to the network, every
first-time supplier in every tenant would poison every other tenant's queue within a day,
and the signal would be worth nothing.

## The cost, stated first rather than last

**A tenant who refuses carelessly, or maliciously, degrades everybody else's queue.** The
network's failure mode is denial of service by false alarm, and nothing here prevents it
— `count` exists so a reader can weigh one client's opinion against several, but that is
weighting, not protection. The reason this is acceptable is the asymmetry above: the
attack costs human attention and cannot move money. It is a real cost and it lands on a
person.

No LLM in this file, by design. Standard library only.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from praetor.types import Finding

__all__ = ["RefusalNetwork", "Refusal", "fingerprint", "apply", "REFUSED_ELSEWHERE"]

# The code a reader sees. `dashboard/language.py` owns the sentence.
REFUSED_ELSEWHERE = "ACCOUNT_REFUSED_ELSEWHERE"


class SaltRequired(ValueError):
    """A refusal network with no salt would publish a queryable list of accounts."""


def _normalise(account: str) -> str:
    """Separators are formatting, not identity. Same rule as praetor/gate.py."""
    return re.sub(r"[^A-Za-z0-9]+", "", account or "").upper()


def fingerprint(account: str, salt: str) -> str:
    """The only representation of an account that may leave a tenant.

    Salted, so the registry cannot be turned back into a list of accounts by anyone who
    obtains it; deterministic, so two tenants holding the same account agree without ever
    exchanging it.
    """
    if not salt:
        raise SaltRequired("a refusal network needs a salt; a default salt is a public one")
    normalised = _normalise(account)
    if not normalised:
        return ""
    return hashlib.sha256(f"{salt}:{normalised}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Refusal:
    """What the network knows about one account, and it is deliberately very little."""
    fingerprint: str
    tenants: int          # how many DISTINCT tenants refused it, never which
    times: int            # how many refusals in total


@dataclass
class RefusalNetwork:
    """Accounts a person somewhere refused to pay.

    Deliberately not a store: it is a small in-memory structure the caller loads from
    wherever their refusals live, so the kernel keeps no database and this file stays
    standard library only.
    """

    salt: str
    _by_fingerprint: dict[str, set[str]] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.salt:
            raise SaltRequired(
                "a refusal network needs a salt; a default salt is a public one")

    def record(self, tenant_id: str, account: str) -> str:
        """A person at `tenant_id` refused to pay `account`. Returns the fingerprint.

        The tenant id is used to count *distinct* refusers and is never stored against
        the fingerprint in a form that can be read back out -- `Refusal` exposes a number,
        not a membership list.
        """
        if not tenant_id:
            raise ValueError("a refusal must come from a tenant")
        fp = fingerprint(account, self.salt)
        if not fp:
            raise ValueError("a refusal needs an account")
        self._by_fingerprint.setdefault(fp, set()).add(tenant_id)
        self._counts[fp] = self._counts.get(fp, 0) + 1
        return fp

    def lookup(self, account: str) -> Refusal | None:
        fp = fingerprint(account, self.salt)
        seen = self._by_fingerprint.get(fp)
        if not seen:
            return None
        return Refusal(fingerprint=fp, tenants=len(seen), times=self._counts.get(fp, 0))

    def check(self, record, asking_tenant: str | None = None) -> list[Finding]:
        """Findings for an invoice whose account somebody has refused before.

        `asking_tenant` is excluded from the count, so a tenant is not warned about its
        own past refusal as though it were outside corroboration. Their own history is
        already theirs; what the network adds is what *other* people found.
        """
        acct = getattr(record, "bank_account", None)
        if acct is None or not getattr(acct, "value", ""):
            return []
        fp = fingerprint(acct.value, self.salt)
        others = {t for t in self._by_fingerprint.get(fp, set()) if t != asking_tenant}
        if not others:
            return []
        n = len(others)
        return [Finding(
            REFUSED_ELSEWHERE, "bank_account",
            f"this account was refused by a person at {n} other "
            f"{'client' if n == 1 else 'clients'}")]


def apply(decision, findings: list[Finding]):
    """Add network findings to a gate decision. It can only ever become more restrictive.

    This function is the boundary the whole file exists to make safe, so it is written to
    be obviously incapable of the dangerous direction rather than merely not to take it:

      * it never removes a finding -- the originals are copied through first;
      * it never returns APPROVED -- that path needs a human and lives in `gate.approve`;
      * if it adds anything at all, the action is ESCALATE.

    An empty `findings` returns the decision unchanged, so a network with nothing to say
    costs nothing. `tests/test_refusal.py` asserts the monotonicity over generated
    combinations rather than trusting this docstring.
    """
    from praetor.gate import Action, GateDecision

    if not findings:
        return decision
    return GateDecision(
        doc_id=decision.doc_id,
        action=Action.ESCALATE,
        findings=[*decision.findings, *findings],
        approved_by=None,      # never carried over: a shared warning cannot ride an
                               # existing approval into a payment
    )
