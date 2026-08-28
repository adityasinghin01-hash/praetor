"""A spending ceiling that survives a cold start.

`praetor/costguard.py` keeps its running total in a file. On a laptop that is right. On
Cloud Run it is a control that fails open: the container filesystem is ephemeral, so the
ledger resets whenever an instance is replaced, and a ceiling that resets is not a
ceiling. DECISIONS #8 already records what that class of bug looks like -- a spend
control that silently returns to full in exactly the situation it exists for.

Automation is what makes it reachable. A pipeline woken by a file landing in a bucket
spends money with nobody watching, so anyone who can write to the bucket can write to the
bill. That is the threat this file exists for.

Firestore transactions are serialisable, so the read-modify-write that the file backend
does under a lock is done here inside a transaction. Concurrent Cloud Run instances
therefore cannot each read the same total and overwrite one another, which is precisely
the undercounting the file backend's lock prevents locally.

    from ingest import ledger
    ledger.install()          # no-op, loudly, if the SDK or credentials are absent

It lives in `ingest/` rather than in the kernel because it is deployment plumbing and
needs a third-party SDK. `praetor/costguard.py` stays standard-library only and never
learns that Firestore exists.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from praetor import costguard

COLLECTION = "praetor_spend"
DOCUMENT = "ledger"


class FirestoreLedger:
    """The running total, in one Firestore document, updated transactionally."""

    def __init__(self, client, collection: str = COLLECTION, document: str = DOCUMENT):
        self._ref = client.collection(collection).document(document)
        self._client = client
        self._tx = None

    @contextmanager
    def lock(self):
        """A Firestore transaction, standing in for the file lock.

        `read` and `write` inside this block go through the transaction, so two instances
        recording at once serialise instead of clobbering each other.
        """
        transaction = self._client.transaction()
        transaction._begin()
        self._tx = transaction
        try:
            yield
            transaction._commit()
        except Exception:
            try:
                transaction._rollback()
            finally:
                pass
            raise
        finally:
            self._tx = None

    def read(self) -> dict | None:
        snapshot = self._ref.get(transaction=self._tx) if self._tx else self._ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        # Only the fields costguard.Spend knows about. An extra key from a future version
        # must not crash the ceiling -- failing closed on spend is right, failing closed
        # on a schema addition is not.
        return {k: v for k, v in data.items()
                if k in {"usd", "calls", "input_tokens", "output_tokens", "pages"}}

    def write(self, data: dict) -> None:
        if self._tx is not None:
            self._tx.set(self._ref, data)
        else:
            self._ref.set(data)


def install(project: str | None = None) -> bool:
    """Point costguard at Firestore. Returns whether it took effect.

    Returns rather than raises, and the caller decides. A deployment that cannot reach
    Firestore should refuse to spend rather than spend against a ledger that forgets --
    `ingest/server.py` treats False as fatal, which is the decision this function
    deliberately does not make for it.
    """
    try:
        from google.cloud import firestore
    except ImportError:
        return False
    try:
        client = firestore.Client(project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"))
        ledger = FirestoreLedger(client)
        ledger.read()                      # prove it is reachable before relying on it
    except Exception:  # noqa: BLE001
        return False
    costguard.use_ledger(ledger)
    return True
