# From here to shipped

Written 28 Aug 2026. Eight phases. **Finish one before starting the next**, and each leaves
the product coherent if work stops there.

This is the plan of record. `docs/ROADMAP.md` is the earlier score-driven version and is kept
for its reasoning; where they disagree, this file wins.

---

## Where things stand

| | |
|---|---|
| Tests | **669 passing tests**, and 605 of them with only `pytest` installed; plus **33** frontend tests including an accessibility pass |
| Kernel | `praetor/` imports nothing outside the standard library, and nothing from the web layer |
| Live | https://praetor-836128159455.asia-south1.run.app · `/app` is the three-tab UI |
| Rules baseline | precision 0.800 · recall 0.963 · **F1 0.874** frozen corpus; **recall 1.000 · F1 0.879** on the wider one, once the invoice is checked against itself |
| Adjudication | 65 → 47 human touches, precision 1.000 · **18 of the 19 removals that existed — 94.7% of the ceiling** |
| Canary | **0 false positives / 350**; every prose-sourced account refused, all **20** injected documents caught |
| Front door | real PDF → Document AI → kernel, **30/30 fields** across 5 layouts, ₹0.88/page |
| Second path | **0.997** held out by layout · **0 of 100** payloads beat both paths · false alarms on clean documents **0.545 → 0.045** |
| Filter, measured | Model Armor flags **7 of 8** that already failed, **3 of 12** that work |
| Automation | a PDF in a bucket is a queue entry in **6.45s**, no manual step |
| The moat | a merged vendor master pays the wrong account **12 of 12**; refusals cross, trust never does |
| Shippable | infrastructure as code, `0 to destroy`; the queue serves **~170 req/s**, flat under concurrency |
| Benchmark | **VSB**, 700 cases, the first for value substitution rather than agent action; a fully compromised reader scores **0 of 480** at **0.955** utility |
| Fine-tune | on-device reader **6x better** on a trained layout; over all five folds, **2.7x to 0.9x** on unseen ones and **0.1x** on the outlier |
| Attacker moves second | nine strategies, budget 1 to 9, **0 of 450** reach the sink |
| Spent to date | about **₹27 of credit**. Money has never been the constraint |

**Phases 1 to 8 are done.** What remains is Aditya's, and it is listed below.

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

## Phase 6 — The product surface · **DONE**

**FastAPI first**, as the plan required, and the swap is provable:
`test_both_transports_return_the_same_json` issues the same request through
`dashboard/serve.py` and `dashboard/asgi.py` and compares. `serve.py` stays, standard
library only, so `make demo` still runs with nothing installed. Paging is a window and
never a filter; live updates stream a version marker and never content; uploads run the
same `ingest/pipeline.py` Eventarc drives.

**Then the frontend.** React and TypeScript in `web/`, 49 KB gzipped, holding no data of
its own. `j`/`k` move, `Enter` opens, `/` searches, `Esc` closes, and focus follows the
cursor so the same keys work for a screen reader. 18 frontend tests including an
`axe-core` pass with zero violations. Severity reaches the screen as words, a shape and a
position — never colour alone.

The language rule now covers the frontend, and the two word lists cannot drift: adding a
word to `language.FORBIDDEN` without adding it to the frontend check fails the build.

Building it found four defects, and one of them only a screenshot could find: the amount
rendered in the wrong column because `grid-row` without an explicit `grid-column` let
auto-placement move it. Every test passed. See `FINDINGS.md` §22.

**Not done, and stated rather than implied:** the React app has no sign-in — it depends
on a cookie the old transport establishes. "What we stopped" is a placeholder and the
interactive attack demo is not ported; both still work on the plain `/app` page. And the
`axe` pass runs under jsdom, which cannot compute colour, so contrast is hand-designed
and not machine-verified.

## Phase 7 — Actually shippable · **DONE**

**Infrastructure as code** (`terraform/`): the bucket, both Cloud Run services, Eventarc,
Workflows, Scheduler, the secret, the APIs and the IAM. Validated, with import blocks that
adopt the live resources. **Not applied** — and reading the plan is why: the first one
would have retagged the live queue with the ingest image and changed the ingest service's
ingress. Current plan is `6 to import, 22 to add, 4 to change, 0 to destroy`.

**Staging** is the same code with one variable. Described, not created — Firestore,
Storage and Artifact Registry bill at rest.

**Secrets out of files:** production refuses to read a credential off its own disk and
names the redeploy command instead.

**Tracing on by default in production**, and to stdout rather than a file — a Cloud Run
filesystem is ephemeral, so a file trace is one nobody can read.

**Backups and retention**, scoped to what is actually irreplaceable: the approvals.
Firestore daily backups kept 7 days; inbox objects deleted at 90 days, versioning on. The
two retentions are aligned so a backup cannot outlive the deletion policy.

**Load tests:** the queue serves ~170 requests/second and **does not get faster with
concurrency** — flat from 1 worker to 64, because every request rebuilds the whole queue.
That is 14 million a day against an analyst doing 300, so it is a ceiling worth knowing
rather than a problem. Zero failures at every level; the rate limiter refuses 682 requests
cleanly with `Retry-After` and fails none.

**The ERP seam** (`praetor/erp.py`): four questions as a Protocol, refusing anything that
carries document provenance. Defined and tested; **the kernel does not use it yet**, and a
test asserts that so the docs cannot start implying otherwise.

Not done: `google_workflows_workflow` has no import support in the provider, so the live
sweep cannot be adopted without recreating it. Stated in `terraform/imports.tf`.

## Phase 8 — The write-up · **DONE**

Three things, all three built and measured. `FINDINGS.md` §24, §25, §26.

**The benchmark that did not exist** (`benchmark/`). **VSB, 700 cases**: 480 attacks
across 23 techniques, 5 injection sites, 4 attacker account shapes and 5 layouts, plus
**220 cases with no attack in them** — controls, legitimate VAT-number decoys, and
remittance-change *wording* over the vendor's *own* account. Every case carries the
document twice, as spans and as flat text, so a span-based architecture and a plain-text
extractor are scored by one function on one document. Scored on the **value returned**,
never a span id and never a tool call, which is the gap §3 found and no adapter closes.

The scorer refuses to produce a single figure: attack success rate beside utility, and a
test asserts that escalating everything scores **0.000 and 0.000**. Three reference runs
ship, all with **no model at all** — the reader is replaced by a deterministic oracle or a
fully compromised one, so anybody can reproduce the numbers with no key and no GPU.

The result is a trade stated as arithmetic. With a **fully compromised reader** — it hands
the attacker's span over on every case — the architecture scores **0 of 480**, at a cost of
**0.545 escalation on clean documents**. Turn the second path off and 20 of 480 succeed and
utility is perfect. All 20 are the same case: the parser labelled the attacker's span as
the payment field, so the canary is blind by construction, and every such case says so.

**The fine-tune** (`finetune/`, runbook in `finetune/README.md`). LoRA on Gemma 3 1b, on an
M1, 27 minutes, no cloud. It **worked and did not transfer**: F1 0.051 → **0.304** on a page
template it trained on, populating `bank_account` for the first time in this project, and
0.074 → **0.007** on one it had never seen. It learned the training layouts' left margins
and wrote them over the coordinates in front of it — three of four coordinates copied
exactly, the fourth invented. **Held out by document this would have been published as a 6x
win.** The layout hold-out is the only reason the second number exists.

And the point: accuracy fell by an order of magnitude, **396 invalid answers were refused
and 0 reached the record**. A model we made worse ourselves, in a new way, and the 92 lines
did not care.

**The adaptive-attack evaluation** (`eval/run_adaptive.py`). Nine strategies ordered by how
much of `praetor/` the attacker has read — prose, bare tokens, placement, label capture,
shape matching, and a compromised vendor mailbox printing only its own account. 50
documents, 500 trials, attack success **flat at 0.000 from budget 1 to budget 9**, with a
clean document payable 50 of 50 so the zero is a defence and not a broken harness.

Two vacuous results were caught on the way and both are now tests: the carrier sitting in
its own vendor master, and a success predicate (`action == "pay"`) that could never be
true because the gate has no such action.

**Not done, and stated rather than implied:** one fold, not five, on the fine-tune. No
hosted-model run of either the benchmark or the ladder — 700 calls and ~450 calls against a
free tier of 20 per day. The adjudicator half of the ladder is on the local model only, and
§9 already records that it is the conservative one, so it is a weak instrument for the
question. And the repository still has **no `LICENCE` file**, which is what "release the
benchmark" actually requires.

---

## What only Aditya can do

1. ~~Open the Vertex support case, and the card test.~~ **Both dropped 29 Aug.** It was gating three things
   and all three resolved without it: 3.7 was dropped, Rule 4 is measured (§27), and the
   benchmark's reference runs are on-device by design. A card may be tried instead.
2. Approve spend beyond ~₹5,000 of credit.
3. Decide whether Rule 4 ships on. **Now measured** (`FINDINGS.md` §27): on this
   corpus it takes autonomy from 27.7% to **0.0%** and prevents zero wrong resolves,
   because every one of the 18 it removes was correct. Recommendation: leave it off,
   keep the flag, and re-measure on a corpus that has purchase orders behind its
   exceptions.
4. Record the demo video.
5. Publish the blog and social post.
6. Submit on Devpost.

**Nothing written for an audience lives in this repo.** The blog post, the social post,
the demo script and the Devpost text are written fresh at the moment they are posted,
against whatever `FINDINGS.md` says that day. Drafts of those four used to sit in `docs/`
and were a phase behind the code within a week — a stale draft in a repo does not announce
itself, it just gets published. Ask for the text when you are about to post it.

The order agreed 29 Aug: **finish and test the system first, then the frontend, then the
demo video, then the submission.**

Optional: request DocILE access (a human has to ask). The teardown decision is deferred
until the hackathon results are out; credit expires ~25 Sept.

## The ten weaknesses, and where each one stands

Written 29 Aug 2026 after listing every gap this project has, ranked by how badly each
undermines it, and then working the list. **Six moved, two cannot be bought, one is a
judgement call, and one is half done and needs Aditya.**

| # | Weakness | State |
|---|---|---|
| 1 | **Never tested on a real document** | **As far as it goes.** 300 real scanned receipts, sitting unscored in the repo the whole time, are now measured — and they found a 96% false-positive rate no synthetic corpus could (`FINDINGS.md` §29). **Closed as of 29 Aug** at Aditya's decision: sourcing twenty real invoices with payment details was cancelled. So the privileged field has never met real paper, and no sentence anywhere may imply otherwise. |
| 2 | **We wrote the attacks** | **Partly, and the rest needs no code.** Somebody else's payloads were fetched and measured: **0 of 263** public injections can express value substitution at all (§32). That settles why VSB had to exist and does **not** settle the circularity. The instrument for closing it is already built and live — the *Try to break it* tab runs the real kernel with the reader assumed fooled, and `dashboard/attack_log.py` keeps every attempt. **The remaining task is sending two people the link.** |
| 3 | **Only one field guarded** | **Done.** Two fields now — the two that move money — and the arithmetic check that had never existed: recall 0.787 → **1.000** on the wider corpus (§30). |
| 4 | **Nobody has ever used it** | **Cannot be bought.** 0 human decisions on record; the queue ordering has learned nothing and says so. Months of real use, or nothing. |
| 5 | **Cries wolf on clean documents** | **Done.** The worst number in the repo: **0.545 → 0.045**, twelve times fewer false alarms, attack success unmoved at 0 of 480 (§31). |
| 6 | **The agent saves less than it sounds** | **Done, by reframing.** The corpus contains only 19 resolvable exceptions in 65. The agent took **18 of 19 — 94.7% of the ceiling** — and every one was right (§34). The 28% is the corpus, not the agent. |
| 7 | **It does not act** | **Cancelled 29 Aug.** Adding tool calls moves this onto the ground CaMeL, Dromedary, AuthGraph and Zenity already occupy, where their protection needs an agent that clicks and a user giving instructions — neither of which a batch pipeline has. The generalisation that would stay ours (a tool argument must be a reference into a buyer-controlled record, never a value the document supplied) is named in `FINDINGS.md` §25 and deliberately not built. |
| 8 | **No confirmed real incident** | **Cannot be bought.** The threat is arriving, not happening. Say it that way. |
| 9 | **One flavour of paperwork** | **Done.** A second corpus with three account formats, two pages, line items and non-English notes broke three components and exposed an English-only assumption nothing had declared (§28). |
| 10 | **No outside review, legal untouched** | **Half done.** The legal side is researched (§33): the EU AI Act's high-risk list covers natural persons, not suppliers, and SOX has no AI-specific rule. A self-review of this session's kernel changes found a real hole — the fix for §29 opened an attack that no test caught. **An actual outsider has still not looked.** |

**What working the list actually produced:** four defects that shipped and would have stayed
shipped — a 96% false-positive rate on real paper, an attack opened by its own repair, a
rule that passed on missing input, and a translation table two fields out of date. Every
one was found by widening the evidence rather than by rereading the code.

## What no amount of building fixes

**The two data assets are empty.** The attack corpus and the record of human decisions are good
schemas with almost nothing in them. They fill with real usage over months. Build the pipes;
never claim the water.

**No confirmed incident exists.** This attack is anticipated, backed by an observed technique
and a measured fraud category. Say "arriving", never "happening".

**Regulation: looked at once, by an engineer, not by counsel** (`FINDINGS.md` §33).
The EU AI Act's high-risk list covers the creditworthiness of *natural persons*; paying a
supplier is a decision about a company, and the gate's human-only approval falls on the
advisory side of the line the Act draws. SOX has no AI-specific rule at all — it applies
to whatever control you have, human or algorithm, and asks for it documented, tested and
evidenced. **Liability is a third question and neither regime answers it.**

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
