# Architecture decisions

Every entry says what was chosen, what was rejected, why, and **what it costs** — a
decision record with no cost column is advocacy, not design.

Where a decision was made because of something we measured, the measurement is cited.
Where it was reversed, the reversal is here too.

---

## 1. The model handles references, never values

**Chosen.** The reader is shown the document as numbered spans and may answer only with
span IDs. A resolver containing no model looks each ID up in the immutable document and
rejects anything that is not a real span.

**Rejected: sanitising the input.** Strip or escape the dangerous parts of the document
before the model sees them.

**Rejected: a prompt-injection classifier** in front of the reader — Model Armor, a
guardrail, a filter.

**Why.** We measured 20 documented injection techniques against an ordinary extraction
prompt. Twelve worked, and the split is total: every payload that worked reads like
ordinary business correspondence, every payload that failed looks like an attack
([FINDINGS §1–2](../FINDINGS.md)). A classifier is trained on adversarial-looking text,
so it would catch the eight that were already failing and miss the twelve that work.
"Please note our updated banking details" is not a jailbreak — as text it is
indistinguishable from the legitimate sentence. There is nothing to sanitise and nothing
to detect, so the value must never reach the sink instead.

**What it costs.** The reader can still point at the *wrong* span, and the design does
not stop that — it only stops invention. It also requires the document to already be
segmented into spans, which is why §9 exists.

**Enforced by.** `tests/test_invariants.py`, and measured on the live path in
[FINDINGS §10](../FINDINGS.md): 25 of 25 attempts by a weak reader to answer with a
literal value were refused.

**The rejection of a filter is now measured rather than predicted (28 Aug).** The
argument above was a prediction about a product nobody here had run. It has been run:
all 20 payloads through Google Model Armor, three templates, two framings, at the most
sensitive confidence setting — [FINDINGS §19](../FINDINGS.md).

In its most favourable configuration it flags **7 of the 8 payloads the model already
resisted and 3 of the 12 that beat it**. Nine of the twelve are never flagged by any
configuration in either framing — including A18, one of the only two payloads that also
beats the span contract. The prediction was "catches the 8, misses the 12"; the
measurement is 7 of 8 and 9 of 12 missed, which is the same shape and slightly kinder to
the filter than the prediction was.

Two things this does not license. It is **not** a finding that Model Armor is bad: it is
being measured on a task it was not built for, and on text that is trying to jailbreak a
model it works. And it is **not** an argument against deploying one — it is free, it
catches the noisy half, and nothing here says remove it. It cannot be the control that
stops the payment, which is the only claim this decision ever made.

---

## 2. Deterministic code has the last word, not a better model

**Chosen.** The agent's answer is advisory. Three rules run afterwards, all pure Python:
privileged fields, document-claimed authority, tenant isolation.

**Rejected: making the agent harder to fool** — a stronger model, a better system prompt,
self-critique, a second model to check the first.

**Why.** Every one of those raises the cost of a successful attack without bounding it,
and none of them can be tested to a guarantee. Our own run settles it: the agent was
talked into the wrong answer twice — once by a remittance notice, once by a fabricated
approval ticket — and the outcome was correct both times because code it could not argue
with refused ([FINDINGS §6](../FINDINGS.md)). We did not have to make the agent
un-foolable. We had to make being fooled not matter.

**What it costs.** The gate is blunt. It escalates cases a person would wave through, and
that shows up directly as human touches we did not remove.

---

## 3. Write the dumb baseline before the agent

**Chosen.** 118 lines of exact-match-and-tolerance rules, written before any agent
code. (That was the raw line count on the day. The file is 64 lines of code today,
counted the way [FINDINGS §5](../FINDINGS.md) counts them.)

**Rejected: starting with the agent** and adding a baseline later for comparison.

**Why.** The baseline gets F1 0.874 and names the right reason on 100% of its catches
([FINDINGS §5](../FINDINGS.md)). That told us on day two that detection was close to
solved and the agent's job was *adjudication* — reading the note on the invoice and
deciding whether a person needs to see it. Had we built the agent first we would have
spent the project making it detect things a regex already found.

**What it costs.** Two of 54 deviations are missed, both amount spikes that land inside
the supplier's own historical range. A range rule cannot catch those by construction.

---

## 4. An authorisation the document claims for itself is worth nothing

**Chosen.** Approval language on a document counts only if it names a reference in the
buyer's own purchase-order register, **and** the invoice reconciles to the amount that
order was raised for.

**Rejected: trusting in-document references** because they look structured. A ticket
number reads as more official than prose, and is exactly as attacker-controllable.

**Why.** This decision is a reversal. The first adjudication run had one wrong resolution,
caused by an injected ticket — "AP-88213, approved by Finance Director" — that does not
exist. It could not move the money, because a bank account is privileged; it moved the
*decision*, because a tax rate is not. We reported that as an open limitation, named the
fix, then built it ([FINDINGS §8](../FINDINGS.md)). Precision went to 1.000.

**What it costs.** It needs a buyer-side register to check against, which is an
integration we do not have. And it is still scoped: a document that is persuasive while
naming nothing checkable — "agreed on the call last Tuesday" — is not caught.

---

## 5. The register is generated by the buyer, never scraped from documents

**Chosen.** `data/po_register.json` is written by the generator from the orders it issued.

**Rejected: building the register by extracting references from the invoices**, which is
the obvious way to populate it from real data.

**Why.** A register derived from the documents would let a fabricated ticket register
itself and then validate the very thing the check exists to catch. The trusted record has
to come from the side that is trusted, or it is not one.

**What it costs.** In a real deployment this is an ERP integration, and the check is only
as good as the register's coverage. Ours holds a single order, so the "verified" path is
exercised by one document and a unit test.

---

## 6. Approval is a schema constraint, not a code check

**Chosen.** SQLite, with approvals keyed on `(tenant_id, doc_id)`.

**Rejected: appending approvals to JSONL**, which is what the project did until 26 Aug.

**Why.** An append is not a transaction and a file has no uniqueness constraint, so the
same invoice could be approved twice and the log would faithfully record both. A double
approval is a double payment. Making the primary key carry that rule means idempotency
does not depend on a handler remembering to check.

**What it costs.** A database to migrate and keep. JSONL remains the export format so
`results/` still holds the published evidence and `make demo` runs with no database.

---

## 7. Tenant isolation is enforced twice, and fails loudly

**Chosen.** The vendor-master lookup is scoped by tenant and never falls back; and
`gate.evaluate` raises `CrossTenantError` if a record and a pattern from different tenants
are ever put in front of it.

**Rejected: one vendor master with a tenant column**, filtered at the call site.

**Why.** "An account we have seen from this supplier" is only meaningful inside one
client's books. Two clients of the same processor can both buy from Meridian Supply and
hold different accounts for it; a shared master answers *yes* for both, which is the wrong
answer about the wrong company. `tests/test_tenancy.py` demonstrates that bug directly —
the merged master proposes payment where the isolated one escalates. This is also what
forces the agent fleet to stay split: merging them reintroduces it.

**What it costs.** No cross-client intelligence. apexanalytix ships exactly that as a
feature, and we have deliberately given it up.

---

## 8. The spending ceiling fails closed

**Chosen.** A missing ledger means nothing spent; an unreadable one refuses every call
until a person looks. All writes are atomic — temp file, fsync, rename — under a lock.

**Rejected: the original**, which swallowed a parse error and returned a zero balance.

**Why.** The ledger was written with `write_text()`, which truncates before it writes. A
crash in that window left a truncated file that read as "nothing spent", and the ceiling
protecting a live billing account silently reset to full. A control that fails open in
exactly the situation it exists for is not a control.

**What it costs.** A corrupt ledger now stops work until a human intervenes. That is the
intended trade.

---

## 9. Spans come from annotations, and there is no OCR

**Chosen.** The reader consumes pre-segmented annotations — `bbox`, `text`, `fieldtype`.

**Rejected: building an OCR and layout stage**, which is what a real deployment needs.

**Why.** Honestly: scope. The security architecture is what this project is about, and
OCR is a large, well-solved problem that would have consumed the time without testing any
of the ideas here.

**What it costs.** This was the largest gap between the project and a product. **A real
invoice arriving as a PDF had no spans, so nothing downstream could run.** The system had
no front door. It was stated in the README rather than left for a judge to notice.

**Partly reversed, 28 Aug.** Document AI's Invoice Parser returns
`pageAnchor.boundingPoly.normalizedVertices` — the same shape this adapter already
consumed — so `praetor/docai_adapter.py` closes the ingestion half without the kernel
changing at all. A PDF now becomes spans, and five invoices across all five layouts came
back 30/30 on fields at 2.46s and $0.01 a page ([FINDINGS §15](../FINDINGS.md)).

**What is still open, and it is the part that matters.** Those PDFs were rendered from our
own corpus, so they are clean digital text with no scan noise, no line items and no
supplier's idea of a layout. The front door works; it has not been tested on documents
anybody actually sent. And there is a cost the original decision could not have
anticipated: the canary reads a span's *label*, which used to be ground truth from an
annotation and is now the output of a model reading the attacker's document. That is a
real weakening of a security check, written up in FINDINGS §15 rather than absorbed
quietly.

---

## 10. Tracing is off unless asked for, and optional entirely

**Chosen.** Spans carry the taint label, the document hash and the span id. Tracing
activates only with `PRAETOR_TRACE=1`, and if OpenTelemetry is not installed every
tracing function is a no-op.

**Rejected: always-on tracing**, and **a hard dependency** on the SDK.

**Why.** The provenance of a paid value should be answerable from a trace months later,
which is the whole point of the taint label riding along. But a missing tracer must never
be the reason an invoice fails to process, and an ordinary run should not pay for
instrumentation nobody is reading.

**What it costs.** The default run produces no trace, so the evidence only exists when
somebody thought to ask for it in advance.

---

## 11. Local authentication, with a seam for a real provider

**Chosen.** PBKDF2 passwords and hashed session tokens, standard library only. The
approver's identity comes from the session; the request body's opinion is ignored.

**Rejected: Google Sign-In now** — the intended production answer.

**Why.** The segregation-of-duties control rested on a self-declared string typed into a
text box, and that had to stop being true before anything else. OAuth needs a credential
we do not have, and would have blocked the fix on an external dependency. The swap
touches one function body, `auth.authenticate()`: sessions, membership, roles and the
approve path are all unchanged, because none of them know how the identity was
established.

**What it costs.** No TLS, no account recovery, and the demo password is printed on the
sign-in page — deliberately, since a judge cloning the repo has no other way in.

---

## 12. Trust is established by approval, never by arrival

**Chosen.** An account becomes trusted only when a person approved paying it.
`record_approval()` is the sole writer to `trusted_accounts`. Not ingestion, not
extraction, not the agent.

**Rejected: deriving trust from the documents**, which is what
`eval/build_vendor_master.py` does — "accounts we have seen from this supplier", counted
from a directory of invoices.

**Why.** That derivation is correct for *measuring* a detection rule and wrong as a trust
boundary, and the difference is not academic: anyone who can send you invoices can write
to it. Two invoices and an attacker's account is "known". Making approval the only way in
means the segregation-of-duties control does double duty — it authorises the payment
*and* it is the only mechanism that creates trust, so there is no second, weaker path to
audit.

**What it costs.** A cold start has no trusted accounts at all, so every supplier's first
payment escalates. That is the correct behaviour and it is still a cost, paid in human
touches during onboarding.

**Enforced by.** `tests/test_trust_establishment.py`.

---

## 13. A value's origin is checked without reading the value

**Chosen.** A privileged field may only be resolved from a span the document itself
labels as a place that field legitimately lives. `praetor/canary.py` reads the span's
*label*, never its text, and refuses anything else — an allowlist.

**Rejected: a blocklist** of suspicious span kinds ("note", "footer", "other").
**Rejected: reading the note** to decide whether it looks legitimate.

**Why.** The resolver guarantees a value is genuinely in the document. It deliberately
does not care *which* span, and that is the gap an attacker with control of the document
actually uses. Half of that gap is decidable without reading anything: a bank account is
printed in a payment block, never in prose. Because the check never reads the text,
**nothing an attacker writes is an input to it** — which is not true of any other control
here. A blocklist fails open on the first span kind nobody thought of, and the attacker
chooses where their text sits, so it would fail open exactly when it mattered.

Measured on the full corpus: **0 false positives on 350 documents, and 42 of 42
prose-sourced accounts refused — including all 20 that carry an injected payload**
([FINDINGS §12](../FINDINGS.md)). An earlier draft of this line said "42 of 42 injected
documents"; 42 is the number with a free-text span, and 20 of those are injections.

**What it costs.** An allowlist fails closed, so unusual labelling — bad OCR, an unmapped
field type, an unseen layout — escalates rather than pays. Zero false positives on a
synthetic corpus with clean labels is also a soft number; on real documents it will not
be zero, and that is the figure to re-measure once §9 is closed.

---

## 14. A decision must point at a rule that verifies

**Chosen.** `praetor/resolution.py`. The agent's resolve stands only if some
pre-authorised rule's preconditions hold. Four rules, a closed set, every precondition
reading buyer-side records only. **The gate evaluates the rules itself.**

**Rejected: letting the agent name the rule it is relying on**, which is the obvious
shape and the one the plan originally described.

**Why.** [FINDINGS §8](../FINDINGS.md) closed authorisation claims and named what it left
open: a document that is persuasive while claiming nothing checkable. *"This variance was
agreed on the call last Tuesday"* names no reference, so there is nothing to look up and
nothing to refuse. Rule 4 stops asking whether the sentence is false and asks whether
anything the buyer already knows is true. Asking independently, rather than letting the
agent nominate a rule, removes a move: an agent that picks the rule can pick one that
happens to verify for an unrelated reason. It also means the reader contract did not have
to change to get the guarantee.

**What it costs, and this one is unusual.** It ships **off by default**. Turning it on
changes outcomes — resolves that rested on a persuasive note become escalations — which
will lower the 28% in [FINDINGS §6](../FINDINGS.md). Enabling it and re-measuring §6 are
one task, not two, and shipping it silently would leave a published number describing a
system that no longer runs. That is the failure §5 already spent a correction on. So the
property is proven in tests and the corpus-level cost of enforcing it is not yet measured,
and both facts are stated rather than one of them.

---

## 15. The mechanism is extracted; the invoice layer delegates to it

**Chosen.** `praetor/guard.py` — grounding and origin policy with no domain in them.
`praetor/resolver.py` and `praetor/canary.py` became thin adapters over it.

**Rejected: leaving the mechanism inside the invoice code**, and **rejected: copying it**
into a separate reusable module.

**Why.** The claim is that the security-critical path is small, dependency-free and
checkable by anyone. That is far easier to believe about 92 lines with no domain in them
than about a file that also knows what a tax rate is. Copying rather than delegating
would give two implementations of one security check, and the one that drifts is always
the one nobody is looking at. `resolver.py` fell to 42 lines as a result.

**What it costs.** One more indirection between reading the resolver and seeing what it
does. Worth it, but it is a real cost to someone auditing the code for the first time.

**Enforced by.** `tests/test_guard.py` — every import is checked against
`sys.stdlib_module_names`, the file may not import from `praetor`, and an AST scan (with
docstrings stripped) asserts the code contains no invoice vocabulary.

---

## 16. No page holds data

**Chosen.** The three tabs fetch from `/v1/*` on every request. `dashboard/api.py` reads
the pipeline's own output each time it is asked.

**Rejected: rendering data into the page**, which is what `dashboard/build.py` does and
what the committed `index.html` still is.

**Why.** This defect has now happened four times, each time silently, each time found by
a person reading a number rather than by anything failing: a stale exceptions file scored
against the wrong truth set ([FINDINGS §5](../FINDINGS.md)); a committed page serving span
ids from a corpus that no longer existed; a database built before a regeneration
reproducing those ids even after the page was rebuilt; and the committed `results/`
fallback a fresh clone renders from. A stale artifact renders perfectly — it just
describes documents that are gone. So the page holds nothing, and
`tests/test_no_stale_artifacts.py` fails the build if any derived artifact references a
span id the corpus cannot produce.

**What it costs.** The pages need a server, so the committed `index.html` stays as the
open-it-with-no-server convenience — now covered by the staleness test rather than by
someone remembering to regenerate it.

---

## 17. The second opinion is a second *mechanism*, never a second model

**Chosen.** `praetor/pathb.py`. The privileged field is extracted twice. Path A is the
model. Path B scores each span on character ratios and checksums — `praetor/features.py`
contains no vocabulary, no keyword list and no substring match against natural language.
Disagreement, or Path B abstaining, sends the document to a person.

**Rejected: a second model.** A larger one, a different vendor, a self-critique pass, an
LLM judging the first LLM's answer.

**Why.** Two models are one mechanism. [FINDINGS §2](../FINDINGS.md) measured which
injections beat an extraction prompt and the split was total: the twelve that worked read
like ordinary business correspondence. Anything that works by reading is movable by that
class of sentence, so a second reader fails *correlated* with the first — and correlated
failures are exactly what a second opinion is bought to avoid. This is #2's argument
applied one level up: raising the cost of an attack without bounding it is not a control.

The property that makes Path B worth having is not accuracy. It is that the sentence
which moves Path A is **not an input to it**. Measured over 100 trials — 20 payloads
across 5 layouts, both paths reading the same spans of the same document — 8 beat Path A,
**0 beat Path B, and 0 beat both** ([FINDINGS §18](../FINDINGS.md)).

Three mechanisms now read three disjoint things: Path A reads meaning, Path B reads
composition, `praetor/canary.py` reads the document's own label. Nothing an attacker
writes is an input to more than one of them.

**What it costs, and it is not small.**

- **A second path can be beaten too, and completely.** An attacker who stops writing
  prose and prints a bare account-shaped token defeats Path B: accuracy falls to 0.000
  ([FINDINGS §17](../FINDINGS.md)). It abstains rather than being wrong, and the canary
  refuses what gets through, but the second opinion is gone.
- **Abstention is a denial of service.** Under that attack 342 of 350 documents go to a
  person. Nothing here fixes that; it is a cost paid in Priya's time.
- **Human touches on ordinary traffic.** Five escalations per hundred trials, all from
  one payload whose base64 blob reads as account-shaped.
- **It is fitted, so it has to be refitted.** `praetor/pathb_weights.json` is a derived
  artifact of the kind DECISIONS #16 exists because of, and `tests/test_pathb.py` fails
  the build if it describes a corpus that has changed.

**Enforced by.** `tests/test_features.py` — two strings with identical character classes
and opposite meanings must produce the identical vector, and the test asserts the premise
before the conclusion. `tests/test_pathb.py` — standard library only, and no `fit`,
`train` or `partial_fit` in the file, because a path that learns from the traffic it
judges is a path an attacker can teach.

---

## 18. The second path does not read position, and that reverses the plan

**Chosen.** Geometry is computed and **excluded from the shipped fit**. Path B scores 13
character and checksum features; the 11 position features are held out.

**Rejected: the plan.** `docs/PLAN.md` specified Path B as "a classifier over geometry,
character ratios and checksums", and geometry was built.

**Why.** It was measured out. Held out by layout, geometry scores **0.208 alone** and
*costs* 0.020 when added to the rest — but the number that decided it is the adaptive
attack. With geometry in the fit, an attacker printing an account-shaped token low on the
page took **75 documents**. Without it, 67 of those became abstentions and the total fell
to 8 — the 8 being documents with no account of their own, where the attacker's token is
the only account-shaped span on the page ([FINDINGS §17](../FINDINGS.md)).

The reason is worth stating as a principle rather than a result. Geometry teaches the path
that the payment field sits low on the page. **Position is the one property of a document
an attacker fully controls**, so a path that reads position is a path they can write to —
the same failure as reading the text, in a different alphabet.

The hold-out is what found it. Held out by *document*, geometry would have memorised five
templates and looked strong; that is the failure [FINDINGS §10](../FINDINGS.md) already
recorded, where a weak reader scored F1 0.384 by emitting one memorised span id. Held out
by *layout* it scored 0.208. **The methodology the plan insisted on is what refuted the
design the plan specified.**

**What it costs.** Path B now has no way to tell a payment block from anywhere else on the
page, so a legitimate second account-shaped token — a VAT registration — is a real
confusion for it. On the two documents with no account at all it proposes the supplier's
tax ID as payable, and only the origin check stops that.

**Enforced by.** `tests/test_pathb.py::test_the_shipped_fit_does_not_read_position`. The
features are still computed and the fit can still be run with them, because a feature
deleted is a measurement nobody can repeat.

---

## 19. The corroboration layer may only ever escalate

**Chosen.** `praetor/corroboration.py` returns agreement or one of three reasons to
escalate. It has no code path that authorises a payment, and agreement clears nothing —
the origin check, the vendor master, the authority rule and the privileged-field rule all
still run on a corroborated value.

**Rejected: letting agreement release a payment**, which is the obvious use of a second
opinion and the reason to build one.
**Rejected: resolving a disagreement by preferring one path.**

**Why.** Every mechanism that can authorise a payment is a mechanism worth attacking.
A corroboration layer that could release one would be a *new* way to authorise, reachable
by making two paths agree — and an attacker who has already beaten Path A needs only to
add an account-shaped token to get agreement, which [FINDINGS §17](../FINDINGS.md) shows
is cheap. Agreement is evidence, and evidence is not permission.

Preferring a path on disagreement fails the other way. Preferring Path A restores the
single point of failure the second path exists to remove; preferring Path B hands the
decision to the weaker extractor, which on eight documents proposes a tax ID.

**What it costs.** Every disagreement is a human touch, including the ones where Path A
was right and Path B merely could not tell. That is 5 per 100 on the measured run, and it
is the direct price of refusing to break ties.

**Enforced by.** `tests/test_corroboration.py` asserts over every combination of inputs
that `escalates` is false exactly when the two paths named the same span, and that the
outcome object exposes nothing resembling an approval.
