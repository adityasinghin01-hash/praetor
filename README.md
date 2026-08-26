# PRAETOR

An accounts-payable agent that resolves invoice exceptions on its own — and cannot be
hijacked by the document it is reading.

Built for the Google **All Things Agentic Hackathon** (Taskmaster track).

> **New to the repo? Read [TEAMMATE.md](TEAMMATE.md) instead.** It assumes no prior
> context and walks through everything step by step.

![PRAETOR architecture](docs/architecture.png)

---

## The problem

Outsourced AP processors bill **$2.50–$5.00 per invoice**, so every invoice a human has
to touch costs them margin. Even good teams still touch roughly half, because exceptions
— price variances, changed details, missing references — need judgement.

You cannot simply point an agent at the problem, because invoices arrive from outside
the company and anyone can hide instructions inside one.

**We measured that: 12 of 20 injection payloads (60%) persuaded `gemini-3.5-flash-lite`
to hand back an attacker's bank account.** See [FINDINGS.md](FINDINGS.md).

The result that matters is *which* ones worked. Every payload that succeeded reads like
ordinary business correspondence; every payload that failed looks like an attack. A
filter trained to spot adversarial text catches the ones that were already failing and
misses the ones that work. You cannot filter your way out of that — you can only make
sure the value never reaches the payment sink.

## The design

**The model handles references, never values.**

1. Spans come from the document's own annotations — each has a stable `span_id`.
2. The **reader** (Gemma 3 on-device, or Gemini 3.5 Flash-Lite; no tools, no memory)
   sees spans and returns *only* span IDs.
3. The **resolver** (no LLM) looks those IDs up. Anything that is not a real span is
   rejected — so the model cannot invent a bank account.
4. Every resolved value is marked `TAINTED` and carries its `doc_hash` and `span_id`.
5. The **rules baseline** (no AI) flags deviations from what that supplier normally does.
6. The **exception agent** adjudicates the flagged ones. It sees findings and context —
   never raw document text.
7. The **policy gate** (no LLM) has the last word. Three rules run after the agent, all
   deterministic:
   - a tainted account not in the vendor master cannot be paid;
   - an authorisation the document claims for itself counts only if it names a
     reference held in the buyer's own records **and** the invoice reconciles to the
     amount that order was raised for (`praetor/authority.py`);
   - one client's vendor master can never vouch for another's invoice
     (`praetor/tenancy.py`).

   And **the agent can only `propose`, never `approve`**.
8. A human approves. That single act is both the SOX segregation-of-duties control and
   the declassification step — and in `make serve` it is a real button that calls the
   real `gate.approve()`.

---

## Spin up

**Prerequisites:** Python **3.11–3.13** (not 3.14 — `torch` has no wheel for it) and
`make`. Nothing else. No cloud account, no API key, no billing.

```bash
git clone https://github.com/adityasinghin01-hash/praetor.git
cd praetor
make install          # creates .venv, installs 2 dependencies
make demo             # tests + rules baseline + review dashboard
```

`make demo` takes about ten seconds, makes **no network calls and costs nothing**, and
ends by writing `dashboard/index.html` — the queue a human actually works. Open it.

For the queue with working approvals:

```bash
make serve            # http://127.0.0.1:8000
```

Click any document id to open it: the invoice is drawn from its own spans, at their own
coordinates, with the flagged one highlighted and the document hash checked against what
was stored at ingest. What you see is what the reader was shown, and nothing else.

Sign in with a seeded account — the sign-in page shows them, password `praetor`.
`reviewer@acme-industries.test` is an approver; `auditor@acme-industries.test` is a
viewer and gets no approve button at all.

Every flagged value shows its provenance — `TAINTED`, the span it came from, the hash of
the document it came from — and the approve button calls the real
`praetor.gate.approve()`. **The identity comes from the session, not from the page**, so
the browser cannot name who is approving: posting a different `human_id` in the request
body is ignored and the approval records the signed-in user. Approvals land in SQLite,
keyed so the same document cannot be approved twice.

To prove the corpus itself is reproducible rather than committed-and-trusted:

```bash
make verify           # regenerates all 350 invoices from seed, then re-runs the demo
```

The regenerated corpus is byte-identical to the committed one, so `git status` stays
clean and every downstream number lands on the same values.

### Running the parts that call Gemini

Put a key in `.env` as `GOOGLE_API_KEY=...` (or export it), then:

```bash
make attacks          # re-measure the 60% undefended injection rate  (~20 calls)
make adjudicate       # re-measure the agent's effect on human touches (~58 calls)
```

Both are capped by `praetor/costguard.py`, which prices every call against Google's
published rates and raises `BudgetExceeded` **before** the call that would cross the
ceiling. The ceiling is ₹10 and persists to disk, so it holds across runs and days.
Raise it deliberately: `PRAETOR_BUDGET_INR=25 make adjudicate`.

> The Gemini free tier is **20 requests per day per model**, not per minute. A full
> adjudication run needs ~58 calls, so on the free tier it will exhaust quota partway and
> the remaining exceptions fail closed to `escalate` with the reason
> `no model available`. That is the intended behaviour — an unreachable adjudicator must
> never silently resolve an exception — but it is why some dashboard rows show no
> reasoning. See [FINDINGS.md §4](FINDINGS.md).

### Running the reader with no API key at all

The quarantined reader also runs on a small local model, which is the honest form of
"quarantined": the component that reads untrusted text should not be a large privileged
model with network access.

```bash
ollama serve &
ollama pull gemma3:1b
PYTHONPATH=. python3 -c "
from praetor.agents import local_reader
print(local_reader.read({'p0:0.10_0.08_0.52_0.11': 'Acme Trading GmbH',
                         'p0:0.62_0.08_0.92_0.11': 'INV-7781'}).mapping)"
```

No key, no quota, no cost. On our first run it answered `"currency": "USD"` — a literal
value where a reference was required — and the resolver rejected it. That is the design
working, unstaged. See [FINDINGS.md §7](FINDINGS.md).

---

## Reproducing every number we publish

Nothing in this repo is an industry estimate or a figure typed in by hand.

| Claim | Command | Needs a key? |
|---|---|---|
| 39 invariants pass | `make test` | no |
| Rules baseline: **P 0.800 · R 0.963 · F1 0.874** | `make rules` | no |
| Corpus regenerates bit-for-bit | `make verify` | no |
| Dashboard: 65 flagged → 47 human, precision 1.000 | `make dashboard` | no |
| Undefended injection rate: **60% (12/20)** | `make attacks` | yes |
| Agent removes **28%** of human touches, 0 wrong | `make adjudicate` | yes |

## What the tests actually assert

`tests/test_invariants.py` is the security claims expressed as code, so they are
enforced by CI rather than asserted in a README:

- a literal value is not a reference, and never becomes a field;
- a span ID that is not in the document resolves to nothing;
- every value downstream traces back to text physically present in the document;
- a tainted account absent from the vendor master always escalates;
- an approval the document claims for itself does not count unless the buyer's register
  holds the reference — and an IBAN can never be mistaken for one;
- one tenant's vendor master never satisfies another tenant's invoice, and merging them
  demonstrably reintroduces the bug;
- **no input to the gate produces `APPROVED`** — and `approve()` rejects any
  `human_id` beginning `agent:`.

The last one replays the real payloads that compromised the model
(`test_every_payload_that_beat_the_model_is_stopped_by_the_design`) and asserts the
design stops every one *assuming the reader is fully owned*.

## Layout

```
praetor/        types · resolver · gate · baseline_rules · authority · tenancy
                costguard · docile_adapter
praetor/agents/ reader (Gemini) · local_reader (Gemma/Ollama) · exception_agent
eval/           make_invoices · build_vendor_master · find_exceptions · run_eval
                measure_attacks · run_adjudication · fetch_sroie
attacks/        payload taxonomy + public-dataset loader
dashboard/      build.py -> index.html · serve.py, which handles real approvals
docs/           architecture diagram (HTML source + PNG + PDF) and its renderer
results/        the published measurements, so a clean clone reproduces them
tests/          the invariants
```

## Data

- **Constructed corpus (350 invoices, 25 suppliers)** — generated by
  `eval/make_invoices.py` from a fixed seed. **Synthetic, and labelled as such.** It
  exists because ground truth has to be known exactly to score anything.
- **SROIE annotations** — real scanned receipts, used to sanity-check the span pipeline
  against documents nobody in this project wrote.
- **DocILE** (MIT licence) — token-gated, not committed. Vendor patterns are *derived*
  from a corpus; exceptions are *discovered*, not injected.
- **Purchase-order register** (`data/po_register.json`) — the buyer-side trusted record
  that `praetor/authority.py` checks document-claimed approvals against. Generated by
  `make_invoices.py` from the notes it writes, never from the finished documents.
  **Synthetic, and labelled as such.**
- **Prompt-injection payloads** — a technique taxonomy in `attacks/payloads.py`, with
  `load_public()` for re-running against a public dataset.

## Tech stack

Gemini 3.5 (`gemini-3.5-flash-lite`, falling back to `gemini-3.5-flash`) · Gemma 3 via
Ollama · Google ADK · OpenTelemetry. Every model in the fallback chain is Gemini 3.5+;
`gemini-3.1-*` does not meet the hackathon requirement and `gemini-flash-latest` is an
unversioned alias whose version cannot be stated on a submission form.

**Not yet deployed.** Cloud Run, Firestore, Pub/Sub and Cloud Trace are the deployment
target, and the diagram labels them as such. Everything above runs locally today.

## Prior art — an engineering demonstration, not a market claim

Nothing here is new science. The design follows **CaMeL** (Google DeepMind,
arXiv 2503.18813) and **RTBAS** (CMU, arXiv 2502.08966), with related work in Fides,
NeuroTaint, APPA, TraceAegis and MCPShield.

The space is occupied: **Ramp, Vic.ai, AppZen, Pilot** in AP automation;
**Trustpair, nsKnox, apexanalytix, Eftsure, PaymentWorks** in vendor-payment
verification — and their approach beats ours for bank-detail fraud specifically, because
they verify the account is real and owned by the supplier rather than only controlling
what a document is allowed to change. **Rossum**, who publish DocILE, are themselves an
AP document-processing vendor.

The honest claim is narrower: *here is how you build an autonomous AP agent that cannot
be hijacked by the document it is reading.*

## Known limits

- **Authentication is local, and it is a stand-in.** A password proves the identity and
  a session carries it, which is enough to make the approval record mean something. It is
  not an identity provider: there is no TLS on localhost, no account recovery, and the
  seeded demo password is printed on the sign-in page on purpose. Google Sign-In replaces
  the body of one function, `auth.authenticate()`, and nothing downstream changes.
- **The defence is scoped, not total.** The kernel protects privileged sinks, and
  `praetor/authority.py` now also refuses approvals a document claims for itself. What
  neither stops is a document being persuasive while naming no checkable reference at
  all — "agreed on the call last Tuesday" is unverifiable and unflagged. See
  [FINDINGS.md §8](FINDINGS.md).
- **The 20 payloads are hand-authored**, which is circular evidence on its own.
  `load_public()` exists to replace that number with one from a public dataset.
- **The rules baseline misses 2 of 54 deviations**, both amount spikes that land inside
  the supplier's own historical range — undetectable by a range rule, by construction.
- **The corpus is synthetic.** Real documents (SROIE, DocILE) are used for the span
  pipeline, not for the scored exception numbers.
- **The Gemma fallback is a degraded service, not an equivalent one.** On a tax-rate
  exception with a legitimate exemption note, Gemma 3 1b still voted escalate. Safe
  direction to fail in, but it will clear fewer exceptions than Gemini does.
- **No cloud deployment yet**, so there is no throughput, concurrency or dollar-cost
  figure from a real fan-out run.
