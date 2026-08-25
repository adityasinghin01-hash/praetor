# PRAETOR

An accounts-payable agent that resolves invoice exceptions on its own — and cannot be
hijacked by the document it is reading.

Built for the Google **All Things Agentic Hackathon** (Taskmaster track).

> **New here? Read [TEAMMATE.md](TEAMMATE.md) instead.** It is a full step-by-step guide
> that assumes no prior context.

---

## The problem

Outsourced AP processors bill **$2.50–$5.00 per invoice**, so every invoice a human has
to touch costs them margin. Even good teams still touch about half of them, because
exceptions — price variances, changed details, missing references — need judgement.

You cannot simply point an agent at the problem, because invoices arrive from outside
the company and anyone can hide instructions inside one.

**We measured this: 12 of 20 injection payloads (60%) persuaded `gemini-3.5-flash-lite`
to hand back an attacker's bank account.** See [FINDINGS.md](FINDINGS.md).

The result that matters is *which* ones worked: every payload that succeeded reads like
ordinary business correspondence; every payload that failed looks like an attack. A
filter trained to spot adversarial text catches the ones that were already failing and
misses the ones that work.

## The design

**The model handles references, never values.**

1. Spans come from the document's own annotations — each is a stable `span_id`.
2. The **reader** (Gemini Flash, no tools, no memory) sees spans and returns *only* span IDs.
3. The **resolver** (no LLM) looks those IDs up. Anything that is not a real span is
   rejected — so the model cannot invent a bank account.
4. Every resolved value is marked `TAINTED`.
5. The **policy gate** (no LLM) refuses to pay a tainted account that is not in the
   vendor master, and **the agent can only `propose`, never `approve`**.
6. A human approves. That is both the SOX segregation-of-duties control and the
   declassification step — the same mechanism serves both.

## Reproducible testing

Requires Python 3.11–3.13 (**not 3.14** — `torch` has no wheel for it).

```bash
git clone <repo> && cd praetor
python3 -m venv .venv && source .venv/bin/activate
pip install google-genai pytest scikit-learn xgboost pandas numpy

PYTHONPATH=. python3 -m pytest tests/ -q          # expect: 19 passed
```

The 19 tests are the security claims expressed as code. In particular,
`test_every_payload_that_beat_the_model_is_stopped_by_the_design` replays the real
payloads that compromised the model and asserts the design stops every one, assuming the
reader is fully owned.

To reproduce the attack measurement (needs a Gemini API key in `GOOGLE_API_KEY`):

```bash
python3 eval/measure_attacks.py --out out/attacks_undefended.jsonl --delay 5
```

## Tech stack

Gemini 3.5 (`gemini-3.5-flash`, falling back to `gemini-3.5-flash-lite`) · Google ADK ·
Cloud Run · Firestore · Pub/Sub · Model Armor · OpenTelemetry → Cloud Trace.

Every model in the fallback chain is Gemini 3.5+. The `gemini-3.1-*` models do not meet
the hackathon requirement and `gemini-flash-latest` is an unversioned alias.

## Data sources

- **DocILE** (MIT licence) — 6.7k annotated real business documents. Vendor patterns are
  *derived* from the corpus; exceptions are *discovered*, not injected.
- **Public prompt-injection datasets** — the headline attack number.
- **Synthetic, and labelled as such:** purchase orders, vendor master records, and a
  small perturbation control set.

## Prior art — this is an engineering demonstration, not a market claim

Nothing here is new science. The design follows **CaMeL** (Google DeepMind,
arXiv 2503.18813) and **RTBAS** (CMU, arXiv 2502.08966), with related work in Fides,
NeuroTaint, APPA, TraceAegis and MCPShield.

The space is occupied: **Ramp, Vic.ai, AppZen, Pilot** in AP automation;
**Trustpair, nsKnox, apexanalytix, Eftsure, PaymentWorks** in vendor-payment
verification — and their approach beats ours for bank-detail fraud specifically, because
they verify the account is real and owned by the supplier rather than only controlling
what the document can change. **Rossum**, who publish DocILE, are themselves an AP
document-processing vendor.

## Layout

```
praetor/        types · resolver · gate · baseline_rules · docile_adapter · agents/
eval/           measure_attacks · build_vendor_master · find_exceptions
attacks/        payload taxonomy + public-dataset loader
tests/          invariants (the security claims, as tests)
```
