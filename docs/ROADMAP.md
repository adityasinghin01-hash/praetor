# Roadmap to 9

Written 27 Aug 2026. Target: **Architecture 9 · Backend 9 · ML/DL 9 · Frontend 9.**

Baseline today: **Architecture 8.3 · Backend 7.1 · ML/DL 6.6 · Frontend 5.9.**

Every phase states what it moves and by how much. If a phase does not move a numbered
subsection from `docs/RATINGS` it does not belong here.

**Sequencing rule:** stop at any phase boundary and what exists is coherent. Nothing here
is throwaway, and the hackathon snapshot on 29 Aug is just an early boundary.

---

## Phase 0 — Corpus realism · **BLOCKING** · ~1 week

### Why this is first

`eval/make_invoices.py` emits **one layout**. Verified 27 Aug: every field in all 350
invoices sits at an identical bounding box — `payment_iban` is always
`[0.08, 0.78, 0.52, 0.81]`.

That is fine for what the corpus was built for: scoring rules that compare a field to a
vendor's history. It is **fatal** for anything that reasons about position, because a
model trained on it learns the generator's template rather than a property of invoices.

Building the learned Path B on this corpus would produce a classifier that scores ~100%
and proves nothing, and a decorrelation measurement that is fiction. **Do not skip this
phase to get to the interesting one.**

### Work

1. **Layout variation in the generator.** N distinct templates (left/right payment block,
   header/footer totals, single/two column), plus per-document jitter on every bbox.
   Record the template id in the truth file so results can be sliced by layout.
2. **Realistic noise.** Multi-page documents, spans that wrap, near-duplicate labels,
   missing fields, and fields appearing in unexpected places.
3. **Real documents.** Request DocILE access (token-gated, never obtained). Wire SROIE
   properly rather than as a span-pipeline sanity check.
4. **Re-baseline everything.** Every published number moves. Re-run the full FINDINGS
   suite and record the deltas honestly — including any that get worse.

### Moves

| Subsection | From | To |
|---|---:|---:|
| ML 4.7 Dataset | 6.0 | **8.5** |
| ML 4.3 Evaluation rigour | 8.5 | **9.0** |

### Cost, stated plainly

Every headline number in `FINDINGS.md` changes. F1 0.874 will move. The rules baseline
may get *worse* on varied layouts, and if it does that is the honest result and it gets
published. A corpus that only contains one layout was flattering us.

---

## Phase 1 — Learned Path B and the decorrelation result · ~1.5 weeks

The highest-leverage work in the project: one piece of work, four subsections, and the
demo's climax.

### The idea

The privileged field is extracted twice by mechanisms that **cannot fail the same way**:

- **Path A — the model.** Sees numbered spans, returns a span reference. Can be persuaded;
  cannot invent.
- **Path B — a trained classifier over non-linguistic features.** Sees geometry, character
  ratios and checksums. **Never sees an instruction, so no sentence can move it.**

Disagreement, or Path B silence, sends the document to a human.

### Why a trained model and not regex

Regex Path B goes silent on unusual layouts, and silence costs a human touch. A classifier
generalises to layouts it has not seen — which is the whole point of Phase 0 existing.

Critically, **it remains un-injectable**: the features are position, size, digit ratio,
alpha ratio, format class, mod-97 checksum, and distance to neighbouring labelled spans.
There is no text an attacker can write that changes a coordinate.

### Work

1. **Feature extractor** — geometry (x, y, w, h, area, page-relative position), character
   class (digit/alpha/punct ratios, length, casing), format (IBAN pattern, currency
   pattern, date pattern, **mod-97 checksum pass/fail**), and neighbour features
   (distance to nearest span of each type).
2. **Train** a gradient-boosted classifier on 2,835 labelled spans, **grouped by document**
   in cross-validation so no document leaks between folds, and **held out by layout
   template** so generalisation to unseen layouts is what is measured.
3. **Calibrate** and pick an abstention threshold. Path B must be allowed to say "I don't
   know" — that is what routes to a human.
4. **Ablations.** Score with geometry only, text-features only, and both. If geometry alone
   carries it, Phase 0 was insufficient and we go back.
5. **The measurement.** Run all 20 payloads against Path A and Path B independently:

   | | |
   |---|---|
   | Beat Path A | 12 of 20 — already measured |
   | Beat Path B | expected ≈0 — they are prose, not IBANs in a payment block |
   | **Beat both** | **the real attack surface. Nobody has published this number.** |

### Moves

| Subsection | From | To |
|---|---:|---:|
| ML 4.5 Actual ML depth | 3.5 | **8.5** |
| ML 4.8 Novel technique | 5.0 | **8.5** |
| Arch 1.3 Decorrelated extraction | 8.0 | **9.5** |
| Arch 1.2 Grounding core | 8.5 | **9.0** |

### The rule I will hold

**Do not train an injection classifier to raise the ML score.** It contradicts the
project's own thesis, and a judge who sees us arguing filters fail while shipping one
costs more than the points are worth.

---

## Phase 2 — The API · ~1.5 weeks

`dashboard/serve.py` is hand-rolled `http.server` with manual routing. It is the single
lowest-scoring subsection in the project (3.5) and everything the frontend needs sits
behind it. **Build this before the frontend or the frontend gets built twice.**

### Work

1. **FastAPI** with Pydantic request/response models and generated OpenAPI.
2. **Versioned surface** — `/v1/documents`, `/v1/queue`, `/v1/run`, `/v1/approve`,
   `/v1/audit/{doc_id}`, `/v1/trust`.
3. **RFC 7807 `problem+json`** errors. Remove the broad `except Exception` in `serve.py`.
4. **Pagination, filtering and sorting** on the queue, so it survives more than 65 rows.
5. **Rate limiting** and request-id propagation.
6. **WebSocket** `/v1/ws/queue` so rows appear as they escalate.
7. **Uploads** — multipart to Cloud Storage, then Document AI.

**The kernel stays stdlib-only.** The dependency lives in the web layer, so the security
claims remain checkable with nothing installed but pytest. This reverses ADR "FastAPI cut"
and needs its own ADR explaining that the reason changed because the scope did.

### Moves

| Subsection | From | To |
|---|---:|---:|
| Backend 3.1 API design | 3.5 | **9.0** |
| Backend 3.5 Error handling | 6.5 | **8.5** |

---

## Phase 3 — The frontend · ~3–4 weeks · **the long pole**

Start the moment the API *contract* is stable, not when the API is finished.

### Work

1. **Foundation** — React + Vite + **TypeScript**, design tokens, a small component
   library, Vitest for units and Playwright for flows.
2. **Port the queue.** The design is good; it needs a component model, not a redesign.
3. **Build the Gauntlet.** Staged execution with real timings, the counterfactual toggle,
   and the two-path disagreement made visible. **This is the centrepiece and should end up
   the highest-scoring thing in the product.**
4. **Accessibility, properly.** ARIA on every overlay · focus trap and restore on modals ·
   full keyboard paths · contrast audit · `prefers-reduced-motion` · a real screen-reader
   pass. Currently 4.0 and entirely undone.
5. **Responsive.** Real breakpoints, a card layout for the queue on small screens, touch
   targets.
6. **States for everything** — loading, empty, error, offline, partial.

### Moves

| Subsection | From | To |
|---|---:|---:|
| Frontend 2.6 Tech foundation | 4.0 | **9.0** |
| Frontend 2.4 Accessibility | 4.0 | **9.0** |
| Frontend 2.7 Responsive | 4.0 | **8.5** |
| Frontend 2.5 The Gauntlet | 6.0 | **9.5** |
| Frontend 2.8 Visual polish | 7.0 | **9.0** |
| Frontend 2.1–2.3 | ~7.2 | **9.0** |

---

## Phase 4 — Production hygiene · ~2 weeks · parallel with Phase 3

1. **CI/CD** — GitHub Actions: tests, lint, type-check, build, deploy on green.
2. **IaC** — Terraform for Cloud Run, Firestore, buckets, Document AI, budgets.
3. **Staging environment** separate from production.
4. **Secret Manager** and workload identity. No `.env` in production.
5. **Observability** — Cloud Trace wired and **on by default in production**, structured
   JSON logs, metrics, alerting.
6. **Load tests** against the deployment; integration tests against a real instance;
   property-based tests on the resolver.

### Moves

| Subsection | From | To |
|---|---:|---:|
| Backend 3.7 Observability | 6.0 | **9.0** |
| Backend 3.8 Deployment | 7.5 | **9.0** |
| Backend 3.10 Secrets | 6.0 | **8.5** |
| Backend 3.6 Testing | 8.5 | **9.0** |
| Arch 1.8 Auditability | 8.0 | **9.0** |
| Arch 1.9 Scalability | 6.5 | **8.5** |

---

## Phase 5 — The research output · ~2 weeks

1. **Release the benchmark.** First for value-substitution injection in document
   extraction — verified 27 Aug that none exists. Raise n well beyond 20.
2. **Fine-tune the local reader** to emit only span references. Fixes Gemma's F1 0.384.
3. **Adaptive-attack evaluation.** Apply the *Attacker Moves Second* methodology to the
   gate. Plot ASR against attack budget. Expect a **flat line at the privileged sink** and
   a **sloping line at the adjudicator's decision** — publish both.
4. **Write it up.** Phases 1, 3 and 5 together are a workshop paper.

### Moves

| Subsection | From | To |
|---|---:|---:|
| ML 4.4 Measurement contribution | 8.0 | **9.0** |
| ML 4.1 Model usage | 6.5 | **8.0** |
| ML 4.2 Prompt engineering | 7.0 | **8.5** |

---

## Folded in along the way — small, high-value

| Item | Phase | Moves |
|---|---|---|
| **Rule 4** — bound the agent's resolve authority | 1 | Arch 1.4 → 9.0 |
| **Second tenant**, real, with live cross-tenant refusal | 4 | Arch 1.9 |
| **Move the trusted store** fully out of `eval/` into `praetor/` | 1 | Arch 1.6 → 9.0 |
| **Provenance receipt** — signed, exportable, per payment | 4 | Arch 1.8 |
| **Model Armor head-to-head** measured and published | 1 | ML 4.4 |
| **Document AI front door** | 2 | Arch 1.9, Frontend 2.5 |

---

## Timeline

```
week  1   Phase 0   corpus realism            BLOCKING
week  2   Phase 1   learned Path B  ──────┐
week  3   Phase 1   decorrelation result   │
week  4   Phase 2   the API                │
week  5   Phase 2   ──────────────────────┘
week  6   Phase 3   frontend  ────┐   Phase 4 production hygiene  ┐
week  7   Phase 3              │           (parallel)             │
week  8   Phase 3              │                                  │
week  9   Phase 3   ───────────┘   Phase 4  ──────────────────────┘
week 10   Phase 5   benchmark, fine-tune, adaptive eval
week 11   Phase 5   write-up
```

**~11 weeks.** Frontend is the long pole; Phase 1 is the high-leverage one; Phase 0 is the
one there will be a temptation to skip.

## Projected scores

| | Today | 29 Aug snapshot | Week 11 |
|---|---:|---:|---:|
| Architecture | 8.3 | ~8.6 | **9.1** |
| Backend | 7.1 | ~7.3 | **9.0** |
| ML/DL | 6.6 | ~6.8 | **8.9** |
| Frontend | 5.9 | ~6.8 | **9.1** |

**The 29 Aug snapshot barely moves**, and that is the honest consequence of Phase 0 being
blocking. Three days buys a partial Gauntlet and some polish — it does not buy a
trustworthy decorrelation result, because the corpus cannot support one yet.

## What to do about the hackathon

Two options, and it is a real choice:

**A — Submit honestly at ~7.4.** Ship what exists: the grounding core, the gate, the
approvals-gated trust store, the audit view, a partial Gauntlet, and the Model Armor
result. Document decorrelated extraction as designed-not-built, which `DECISIONS.md`
already has a format for. Then continue the roadmap.

**B — Rush Phase 1 on the one-layout corpus.** Produces a demo that looks better and a
number that is not real. **This is the NETRA failure mode** — shipping something known to
be unsound because the deadline was close. Do not.

Recommendation: **A.** The roadmap is worth more than three points on a submission.
