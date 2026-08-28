# From here to shipped

Written 28 Aug 2026. Eight phases. **Finish one before starting the next**, and each leaves
the product coherent if work stops there.

This is the plan of record. `docs/ROADMAP.md` is the earlier score-driven version and is kept
for its reasoning; where they disagree, this file wins.

---

## Where things stand

| | |
|---|---|
| Tests | **508 passing tests**, and 502 of them with only `pytest` installed |
| Kernel | `praetor/` imports nothing outside the standard library, and nothing from the web layer |
| Live | https://praetor-836128159455.asia-south1.run.app · `/app` is the three-tab UI |
| Rules baseline | precision 0.800 · recall 0.963 · **F1 0.874** on 350 invoices, 5 layouts |
| Adjudication | 65 → 47 human touches, precision 1.000 · autonomy 86.6% |
| Canary | **0 false positives / 350**; every prose-sourced account refused, all **20** injected documents caught |
| Front door | real PDF → Document AI → kernel, **30/30 fields** across 5 layouts, ₹0.88/page |
| Second path | **0.997** held out by layout · **0 of 100** payloads beat both paths |
| Filter, measured | Model Armor flags **7 of 8** that already failed, **3 of 12** that work |
| Automation | a PDF in a bucket is a queue entry in **6.45s**, no manual step |
| The moat | a merged vendor master pays the wrong account **12 of 12**; refusals cross, trust never does |
| Spent to date | about **₹27 of credit**. Money has never been the constraint |

**Phases 1 to 5 are done.** Phase 6 is next.

---

## Phase 1 — Close the holes, tell the truth · **DONE**

Rate limiting on the public endpoints, a web-layer security pass (headers, sign-in limits, the
demo password hidden on deployed URLs), every document reconciled with the code, and CI —
including a job that installs only `pytest` and proves the kernel claim on every push.

## Phase 2 — The front door · **DONE**

`praetor/docai_adapter.py`. A real PDF becomes spans through Document AI, and the kernel did
not change: the parser returns `normalizedVertices`, the shape the adapter already consumed.
`DECISIONS.md` #9 partly reversed — see `FINDINGS.md` §15 for what is still open, including the
honest note that the canary is weaker when span labels come from a model rather than an
annotation.

## Phase 3 — The second path, and the number nobody has · **DONE**

`praetor/features.py`, `praetor/pathb.py`, `praetor/corroboration.py`. The privileged
field is extracted twice by mechanisms that cannot fail the same way. 100 trials — 20
payloads across 5 layouts, both paths reading the same spans of the same document — give
**8 beat Path A, 0 beat Path B, 0 beat both** (`FINDINGS.md` §18). No injection classifier
was trained: Path B is fitted to find the payment field, and never sees a span's label at
inference.

Held out by layout, as required — and **that requirement is what refuted the design**. The
plan specified geometry. Geometry scored 0.208 alone, cost 0.020 in combination, and under
an adaptive attack handed over 67 documents that are abstentions without it. It ships
excluded, with a test that fails if it comes back (`DECISIONS.md` #18, `FINDINGS.md` §17).

Three results worth carrying forward:

- **The span contract changes which attack works.** 9 of the 11 comparable payloads that
  beat an undefended prompt stop working once the reader must answer with a span id, and
  the two survivors attack span *selection* rather than value authorship.
- **The first fit scored 1.000 and was worthless** — one shape regex, on a corpus with
  exactly one account-shaped token per page. Against a legitimate VAT number it abstained
  on 342 of 342.
- **Path B can be beaten completely** by an attacker who stops writing sentences, and
  the canary is what stands after that. Two paths do not make an attack impossible; they
  make it work twice, through mechanisms with no common input.

Model Armor was measured rather than argued: **7 of the 8 payloads that already failed, 3
of the 12 that work**, and 9 of the 12 invisible to every configuration in either framing
(`FINDINGS.md` §19, `DECISIONS.md` #1).

## Phase 4 — Automation around the kernel, never inside it · **DONE**

`ingest/`, `workflows/sweep.yaml`, Eventarc, Cloud Run, Cloud Scheduler. A PDF landing in
`gs://praetor-inbox-2026` becomes a record in Priya's queue in **6.45 seconds** with no
manual step, through Document AI, the quarantined reader, the resolver, the canary, the
rules and the gate. The README's standing admission — *"the deployed instance is a queue,
not a pipeline"* — is retired.

**The kernel got no automation dependency, and it is tested three ways**: an AST scan for
`praetor/` importing `ingest`; `ingest` evicted from `sys.modules` with `__import__`
patched to raise, so a lazy import fails too; and the same document run through the
kernel directly and through the pipeline, asserting the outcomes match field for field.

The interesting part was what automating found. **Three defects, all of which cost money
or would have** (`FINDINGS.md` §20):

- A malformed response made Cloud Run return 502 while the service logged 204. Eventarc
  redelivered nine times and every delivery had already called Document AI — **four
  charges for one invoice**. The 502 is fixed; redelivery is not a bug, so the durable
  answer is one claim per object generation, taken before any money is spent.
- **The spending ceiling did not survive a cold start.** A container filesystem is
  ephemeral, so the same recorded spend read Rs 2.64 from Firestore and Rs 0.00 from a
  file. The service now refuses to start without a durable ledger.
- **The canary fired on every clean invoice that arrived as a PDF.** Document AI labels
  the payment span `supplier_iban`; the kernel's allowlist expects `payment_iban`. A 100%
  false-positive rate on the only path that reads real documents, invisible because Phase
  2 scored fields rather than origins — and a test had pinned the wrong value in place.

Not claimed: the deployed pipeline has no vendor history, so every document escalates as
a first-time supplier. The automation is real; the decision quality in the cloud is not
yet the local decision quality.

## Phase 5 — The moat · **DONE**

A real second tenant (`eval/make_tenant_b.py`): `borealis`, 80 invoices, sharing six
suppliers with `acme` and paying every one of them somewhere else. Written beside the
frozen corpus, never over it.

**Isolation, measured rather than fixtured.** Substitute the other client's genuine
account for the same supplier: the isolated master escalates 12 of 12, and a merged
master proposes payment **12 of 12**. Total, not marginal.

**The refusal network** (`praetor/refusal.py`) is the original idea, and it is an
asymmetry: sharing *trust* lets one client's mistake pay another's attacker, sharing a
*refusal* can at worst cause a second person to look. So refusals cross the boundary and
approvals never do. Only a salted fingerprint and a count of clients travel — never the
account, never who refused. The safety property is asserted over every combination of
inputs, and three plausible bugs each fail it. Cost, stated: one refusal sent 13 invoices
at another client to a person.

**Safe retrieval** (`praetor/retrieval.py`): a document may supply a **key**, never a
**query**. A key matches exactly and returns the buyer's record or nothing; a ranking has
partial credit, and partial credit is steerable. Enforced with the taint label that
already exists, so a caller who relabels a document value as buyer-side is refused anyway.

**Queue ordering** (`praetor/queueing.py`): a permutation, never a filter — a ranker that
can drop an item can hide one. It has learned **nothing**, because the record holds 0
human decisions, and `make queue` prints that in those words rather than implying a
ranking. The pipe is built; the water is not claimed.

## Phase 6 — The product surface · **NEXT**

FastAPI first — paging, live updates, uploads — because the frontend gets built twice
otherwise. The JSON contract in `dashboard/api.py` does not change, so it is a transport swap.
Then the real frontend: React and TypeScript, keyboard and screen-reader access, phones, and
the visual design deliberately deferred to here.

## Phase 7 — Actually shippable

Infrastructure as code, staging separate from production, secrets out of files, tracing on by
default, backups and retention, load tests, and the seam where a real ERP plugs in.

## Phase 8 — The write-up

Release the benchmark that does not exist, fine-tune the local reader, run the adaptive-attack
evaluation. Phases 3, 6 and 8 together are a publishable piece of work.

---

## What only Aditya can do

1. Open the Vertex support case — the block is Google's, not ours.
2. Approve spend beyond ~₹5,000 of credit.
3. Decide whether Rule 4 ships on.
4. Record the demo video.
5. Publish the blog and social post.
6. Submit on Devpost.

Optional: request DocILE access (a human has to ask), and decide on 20 September whether to
tear the cloud down.

## What no amount of building fixes

**The two data assets are empty.** The attack corpus and the record of human decisions are good
schemas with almost nothing in them. They fill with real usage over months. Build the pipes;
never claim the water.

**No confirmed incident exists.** This attack is anticipated, backed by an observed technique
and a measured fraud category. Say "arriving", never "happening".

**Regulation is unresearched.** SOX attestation and the EU AI Act on autonomous payment
decisions likely decide who pays when it goes wrong. Nobody has looked.

---

## How to work on this

- **Verify before writing anything down.** Run the thing that produces the number.
- **Assert on every patch anchor** when editing by script; a silent non-match reads as success.
- **Fix causes, not instances.** Stale data was traced through four layers before it stayed fixed.
- **Turn each repeated mistake into a test**, then reintroduce the bug to check the test fails.
- **Publish numbers that get worse.** The weak reader's F1 fell 0.384 → 0.040 when the corpus
  was fixed, and that is in `FINDINGS.md` with the reason.
- **No code words on any screen.** `dashboard/language.py` owns every sentence a person reads,
  and tests fail the build if a finding reaches a screen untranslated.
