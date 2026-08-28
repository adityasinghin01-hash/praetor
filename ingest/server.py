"""The Cloud Run service Eventarc wakes when a PDF lands in the bucket.

    gs://praetor-inbox-2026/invoice.pdf
        -> Eventarc (google.cloud.storage.object.v1.finalized)
        -> this service
        -> ingest/pipeline.py  (Document AI -> spans -> reader -> resolver -> canary
                                -> rules -> gate)
        -> Firestore, where Priya's queue reads it

`docs/PLAN.md` Phase 4 is one sentence about what this may not do: **the kernel gets no
automation dependency.** So this file is a courier. It parses an event, fetches bytes,
calls `ingest/pipeline.py`, writes the outcome, and has no opinion about any of it.
`tests/test_ingest.py` asserts the kernel decides identically with this whole layer
absent.

## Three refusals, all deliberate

**It refuses to start without a durable ledger.** `praetor/costguard.py` keeps its running
total in a file, and a container filesystem is ephemeral -- so on Cloud Run the ceiling
protecting a live billing account resets on every cold start. Measured: the same spend
reads as Rs 2.64 through Firestore and Rs 0.00 through the file after a restart. A
pipeline triggered by a file landing in a bucket spends money with nobody watching, so
anyone who can write to the bucket could otherwise write to the bill. If Firestore is
unreachable this process exits rather than serving with a ceiling that forgets.

**It refuses to retry a document it cannot process.** A failure becomes a visible record
with an escalate action and returns 204, because a 500 makes Eventarc redeliver -- and a
document that fails deterministically would then be re-parsed by Document AI, at a
penny a page, forever. Retrying a permanent failure is a way to spend money in a loop.

**It cannot approve anything.** The gate's ceiling is PROPOSE_PAY here as everywhere
else. Automation prepares work for a person; it does not replace them.

## Configuration

    PRAETOR_PROJECT          GCP project (default praetor-run-2026)
    PRAETOR_INGEST_READER    "none" (default) or "gemini"
    PORT                     Cloud Run sets this

The reader defaults to **off**, and that is a safety default rather than a limitation:
with no reader the pipeline grounds nothing and escalates, which is honest, instead of
quietly substituting Document AI's own field values for the reader's answer and
bypassing the guarantee the whole system is about.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest import ledger, pipeline  # noqa: E402
from praetor import costguard  # noqa: E402

PROJECT = os.environ.get("PRAETOR_PROJECT", "praetor-run-2026")
READER = os.environ.get("PRAETOR_INGEST_READER", "none").strip().lower()
COLLECTION = "praetor_ingest"
SEEN = "praetor_ingest_seen"    # one document per object version, claimed once


def _token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def fetch(bucket: str, name: str) -> bytes:
    """Download one object. urllib, so the image needs no storage SDK."""
    url = (f"https://storage.googleapis.com/storage/v1/b/{urllib.parse.quote(bucket)}"
           f"/o/{urllib.parse.quote(name, safe='')}?alt=media")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def reader():
    """The quarantined reader, or None.

    Imported lazily and only when asked for, so a deployment with the reader off carries
    no model client at all -- the property the Dockerfile comment has always claimed for
    the queue service, kept true for this one.
    """
    if READER != "gemini":
        return None
    from praetor.agents import reader as reader_mod

    client = reader_mod._client()
    return lambda spans: reader_mod.read(spans, client=client).mapping


def store_outcome(outcome: pipeline.Outcome, bucket: str, name: str,
                  generation: str) -> None:
    from google.cloud import firestore

    client = firestore.Client(project=PROJECT)
    doc = {**outcome.as_dict(), "bucket": bucket, "object": name,
           "generation": generation, "received_at": firestore.SERVER_TIMESTAMP}
    client.collection(COLLECTION).document(outcome.doc_id).set(doc)


def claim(bucket: str, name: str, generation: str) -> bool:
    """Claim this exact object version, once. False means somebody already has it.

    **Event delivery is at-least-once, and that makes a duplicate delivery a duplicate
    charge.** Measured, the first time this service ran: a malformed empty-body response
    made Cloud Run return 502, Eventarc redelivered five times, and Document AI billed a
    page on every one -- $0.05 for a single invoice. The 502 was a bug and is fixed.
    Redelivery is not a bug: it is the platform's contract, so a pipeline that spends per
    document must be idempotent or it is a way to bill the account in a loop.

    `generation` is GCS's id for one specific version of one object, so re-uploading the
    same file legitimately re-processes it while a redelivered event does not.

    The claim is written in a transaction BEFORE the money is spent. That direction is
    deliberate: a crash after claiming loses a document, which a person can see and
    re-upload, while a crash before claiming charges twice, which nobody sees.
    """
    from google.cloud import firestore

    client = firestore.Client(project=PROJECT)
    key = f"{bucket}__{name}__{generation}".replace("/", "_")
    ref = client.collection(SEEN).document(key)

    @firestore.transactional
    def _claim(transaction):
        if ref.get(transaction=transaction).exists:
            return False
        transaction.set(ref, {"bucket": bucket, "object": name,
                              "generation": generation,
                              "claimed_at": firestore.SERVER_TIMESTAMP})
        return True

    return _claim(client.transaction())


def handle(event: dict) -> pipeline.Outcome | None:
    bucket = event.get("bucket") or ""
    name = event.get("name") or ""
    generation = str(event.get("generation") or "")
    doc_id = os.path.basename(name).rsplit(".", 1)[0] or name

    if not claim(bucket, name, generation):
        return None                       # already processed; costs nothing to say so

    pdf = fetch(bucket, name)
    out = pipeline.process(pdf, doc_id, read=reader())
    store_outcome(out, bucket, name, generation)
    return out


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                    # noqa: N802
        # Cloud Run's own health probe, and a way to see which ledger is in force.
        body = json.dumps({"ok": True, "ledger": costguard.ledger_name(),
                           "reader": READER, "spend": costguard.report()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                                   # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            event = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._done(400, {"error": "not JSON"})

        if not event.get("name"):
            # Not an object event we understand. 204 rather than 400: Eventarc retries a
            # 4xx, and retrying something we will never understand is a loop.
            return self._done(200, {"skipped": "no object name"})
        if not str(event["name"]).lower().endswith(".pdf"):
            return self._done(200, {"skipped": f"not a pdf: {event['name']}"})

        try:
            out = handle(event)
            if out is None:
                self.log_message("%s", json.dumps(
                    {"object": event.get("name"), "skipped": "already processed"}))
                return self._done(200, {"skipped": "already processed"})
            self.log_message("%s", json.dumps({"doc": out.doc_id, "action": out.action,
                                               "codes": out.codes, "usd": out.usd,
                                               "seconds": round(out.seconds, 2),
                                               "error": out.error}))
            return self._done(200, {"doc_id": out.doc_id, "action": out.action})
        except Exception:  # noqa: BLE001
            # A failure we did not anticipate. Log it and still return 200: a redelivery
            # would re-run Document AI and charge for the page again.
            self.log_message("unhandled: %s", traceback.format_exc()[-800:])
            return self._done(200, {"error": "logged, not retried"})

    def _done(self, code: int, payload: dict) -> None:
        """Always a body, always a matching Content-Length.

        This sent a Content-Length with no body. Cloud Run turned that into a 502,
        Eventarc treated the 502 as a failure and redelivered, and every redelivery
        charged another Document AI page. A response the platform cannot parse is not a
        cosmetic bug when the retry costs money.
        """
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):                   # noqa: A003
        sys.stderr.write(f"{fmt % args}\n")


def main() -> None:
    if not ledger.install(PROJECT):
        # Deliberately fatal. Serving with a ceiling that forgets is worse than not
        # serving: the ledger is the only thing standing between a bucket and the bill.
        sys.exit("REFUSING TO START: no durable spend ledger (Firestore unreachable). "
                 "praetor/costguard.py would fall back to a file, and a Cloud Run "
                 "filesystem is ephemeral, so the ceiling would reset on every cold "
                 "start.")
    port = int(os.environ.get("PORT", "8080"))
    print(f"ingest listening on :{port}  ledger={costguard.ledger_name()}  "
          f"reader={READER}  {costguard.report()}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
