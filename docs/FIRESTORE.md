# Running on Firestore

PRAETOR keeps its state behind one module, so it has two backends: SQLite by default, and
Cloud Firestore when you ask for it.

**Why both.** SQLite means `make demo` runs for anyone with no account, no card and no
network — which is what lets a judge reproduce every number in this repository. Firestore
is Google Cloud infrastructure, which a laptop database is not. Neither replaces the
other, and the default stays local.

Everything above the store — the approve path, the queue, the dashboard — is written
against one interface and does not know which backend it is talking to.

---

## Setup — about five minutes, no card

Firestore runs on the Firebase **Spark** plan: 1 GB stored, 50,000 reads and 20,000
writes a day, free, **no billing account and no payment method**.

**1. Create the project.** Go to [console.firebase.google.com](https://console.firebase.google.com),
*Add project*, name it `praetor`. Turn Google Analytics **off** — it is not needed and it
asks more questions.

**2. Create the database.** In the left menu: *Build → Firestore Database → Create
database*. Choose **production mode** and a region near you (`asia-south1` for India).
Production mode denies all client access by default, which is what you want: everything
here talks to Firestore as a service account, never from a browser.

**3. Make a service account key.** In the Google Cloud console for the same project:
*IAM & Admin → Service Accounts → Create service account*. Name it `praetor-app`, grant
it the **Cloud Datastore User** role, then *Keys → Add key → JSON*. A file downloads.

**4. Point the project at it.**

```bash
mkdir -p ~/.praetor
mv ~/Downloads/praetor-*.json ~/.praetor/firestore-key.json

export GOOGLE_APPLICATION_CREDENTIALS=~/.praetor/firestore-key.json
export GOOGLE_CLOUD_PROJECT=praetor          # your project id
```

**Never commit the key.** `.gitignore` covers `*.json` under `~/.praetor`, but the safest
habit is keeping it outside the repository entirely, which is why the path above is in
your home directory.

---

## Use it

```bash
pip install google-cloud-firestore

PRAETOR_BACKEND=firestore make db        # load the results into Firestore
PRAETOR_BACKEND=firestore make serve     # the queue, reading and writing Firestore
```

Without `PRAETOR_BACKEND=firestore`, nothing changes and SQLite is used as before.

Approve an invoice in the queue, then open *Firestore Database* in the Firebase console:
the `approvals` collection gains a document with the approver, the finding codes and the
timestamp. That is the write path, live, in Google Cloud.

---

## What is genuinely different between the backends

One thing, and it is worth stating rather than glossing.

SQLite enforces **one approval per document** with `PRIMARY KEY (tenant_id, doc_id)`. A
duplicate is a constraint violation — the database refuses it, and no code has to
remember to check.

Firestore has no composite primary key. The same rule is enforced by a transaction that
reads the approval document and aborts if it already exists. Firestore transactions are
serialisable, so two concurrent approvals cannot both observe the document as unapproved
and the guarantee still holds — but it now lives in application code rather than in the
schema, which is a weaker place for it.

`tests/test_firestore_store.py` pins it as hard as the SQLite version is pinned, for
exactly that reason.

---

## Free-tier limits

| | Spark plan, per day |
|---|---|
| Stored data | 1 GB total |
| Reads | 50,000 |
| Writes | 20,000 |
| Deletes | 20,000 |

Loading the 65-document exception queue costs roughly 200 writes. You are not going to
approach these limits, and Spark **blocks at the limit rather than billing you** — which
is the whole reason to stay on it rather than upgrading to Blaze.
