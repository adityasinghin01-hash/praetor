# Competitive landscape

Swept 27 Aug 2026. This is meant to be the last full sweep — add to it rather than
redoing it.

**How to read the sourcing.** Every entry is marked:

- **[P]** primary — the company's own docs, a repo I read, a paper, a government report
- **[S]** secondary — trade press, analyst blogs, review aggregators
- **[V]** vendor marketing — the company's own claims about itself, unverified

Treat **[V]** accuracy and performance numbers as advertising until reproduced. Several
benchmark claims below are run by the vendor being measured, and that is noted where it
applies.

**Confidence on internals.** Frontend/backend stacks for private companies are mostly
not public. Where I could not establish something, it says so rather than guessing.

---

# 1. Market context

| | | |
|---|---|---|
| Prompt injection rank | **#1 vulnerability for deployed AI agents**, 2026 | OWASP LLM Security Project **[S]** |
| Attack growth | **+340% YoY** | OWASP 2026 LLM Security Report **[S]** |
| Agentic AI security funding | **$392M** in ~2 weeks around RSAC 2026 | **[S]** |
| AI risk platforms | 12 of 27 disclosed deals, $230.5M (~35%), to July 2026 | **[S]** |
| BEC losses 2025 | **$3.05B** reported, 24,768 complaints, 86% via wire/ACH | FBI IC3 2025 **[P]** |
| BEC 3-year | $2.94B → $2.77B → $3.05B | FBI IC3 **[P]** |
| AI-related crime | First tracked 2025: 22,000+ complaints, ~$900M | FBI IC3 **[P]** |
| Injection in the wild | "Crossed from proof-of-concept to live exploitation", Apr 2026 | Cloud Security Alliance **[P]** |
| Delivery techniques in use | **22**, "organized tooling rather than isolated experimentation" | Unit 42 **[S]** |
| Malicious activity trend | **+32%** Nov 2025 → Feb 2026 | Google **[S]** |
| Cost per invoice | $9.40 average, **$2.78 best-in-class** | Ardent Partners 2025 **[S]** |
| Touchless rate | 32.6% average, **49.2% best-in-class** | Ardent Partners 2025 **[S]** |

### The single most useful market fact

The canonical example the industry uses to explain the #1 AI security risk of 2026 is
**PRAETOR's exact threat model**:

> *"An AI agent built to process vendor invoices reads emails, checks amounts, and routes
> payments... A line embedded in the footer of an invoice instructs one agent to redirect
> a payment."* **[S]**

### And the fact that limits what we may claim

**There is no publicly confirmed incident of an AI document pipeline being injected into
a fraudulent payment.** Every invoice-injection case study found is illustrative. Unit 42
observed web-based indirect injection in the wild; nobody has published a document-pipeline
breach. We defend an *anticipated* attack backed by an *observed* technique and a
*measured* fraud category. Never imply more than that.

---

# 2. ERP / hyperscaler agentic AP — the existential tier

These are the ones that could make PRAETOR redundant, and they all shipped in 2026.

## Microsoft — Payflow Agent (Dynamics 365 Finance)

**What it is [S]** Microsoft's most autonomous finance agent. Monitors payment queues,
identifies invoices ready for payment, **verifies vendor banking details against master
data**, executes payment runs within configured parameters, posts payment journals —
**without human intervention for in-policy transactions.**

**Architecture [S]** Exception-based autonomy. Human review triggered only by: new
vendors, amount threshold breaches, or data mismatches. Dynamics separately provides
**vendor bank account approval workflows** so supplier bank-detail changes are reviewed
before taking effect.

**Availability [S]** Dynamics 365 Finance 10.0.x Wave 1 2026, requires Copilot for
Finance licensing. Not on older versions or on-prem AX.

**Claimed impact [V]** 70–80% reduction in AP processing labour.

**Injection posture** No public statement. The agent extracts fields from invoices; if
that extraction is an LLM over untrusted PDFs, the surface is open. Microsoft has
`dromedary` (§6) in-house as research, with no public link to Payflow.

**Relevance — read this carefully.** Microsoft has independently built PRAETOR's *policy*
layer: check the account against master data, escalate exceptions, gate bank-detail
changes behind approval. That is the vendor-master rule and the approvals-gated trust
model, shipped by Microsoft. **What they have not publicly addressed is the extraction
boundary** — that the model reading the document must not be able to author the value.
That gap is precisely PRAETOR's contribution, and it is now the *only* part that is
uncontested.

## SAP — Joule / AP Assistant

**What it is [V]** Orchestrates specialised AI agents (Joule Agents plus custom).
Automates invoice receipt, extraction, posting, payment scheduling "with minimal human
involvement." Processes payment requests from documents and emails, initiates payments.
**Continuously monitors invoices, suppliers, POs and expenses to detect anomalies and
potential fraud.** Handles invoice exceptions autonomously or guides users.

**Injection posture** No public statement found.

**Relevance** "Detect anomalies and potential fraud" overlaps the rules baseline.
Autonomous exception handling overlaps the adjudicator.

## Oracle — Payables Agent (Fusion Cloud ERP)

**What it is [V]** Multi-channel ingestion (email, portals, EDI/e-invoicing, PDF);
extracts and normalises; **matches to POs and receipts** (three-way matching); creates
distributions and accounting; **applies tax, policy and fraud checks**; routes for
approval and payment.

**Injection posture** No public statement found.

**Relevance** The most complete overlap of the three. Oracle ships three-way matching and
policy/fraud checks natively — which is the "Counterparty axis" we were treating as a
differentiator. It is commodity at the ERP tier.

### Sector conclusion

**Rules, PO matching, exception routing and master-data verification are commoditised by
Microsoft, SAP and Oracle.** Any pitch that leads with those is competing with the three
largest enterprise software vendors on their home ground. The uncontested ground is the
*extraction→policy boundary* and the *injection threat model*.

---

# 3. AP automation specialists

## Vic.ai

**What it is [V]** AI-first AP automation. End-to-end autonomous invoice processing.

**Architecture [V]** Proprietary deep-learning models for accounting workflows. Ingestion
via email, desktop upload, mobile photo, EDI, API, SFTP. Continuous learning — each user
correction strengthens the model.

**Training data [V]** **1 billion invoices.** Has processed 535M+ invoices.

**Accuracy [V]** 97–99%. Claims to surpass human accuracy. Up to 355% improved capacity
per FTE, 80% faster processing.

**The autonomy mechanism — the key competitive fact [V]** *"Define confidence thresholds,
so only invoices meeting your criteria are processed automatically, while others are
routed for review."*

**Pricing [S]** Custom/enterprise. No published per-invoice rate.

**Injection posture** None stated.

**Relevance — the sharpest contrast available.**

> Vic.ai gates autonomy on **how confident the model is.**
> PRAETOR gates on **whether an independent source agrees.**

A confidence threshold is the control an injection is *best* at defeating: a well-crafted
injection produces a **high-confidence wrong answer**. Confidence measures fluency, not
truth. An attacker does not need to make the model uncertain — only confidently wrong,
which is easier.

Secondary concern: if the model continuously learns from processed invoices, the training
set is attacker-reachable.

## AppZen

**What it is [V]** Agentic AI for AP and expense management. "Autonomous AP."

**Architecture [V]** **200+ proprietary "ZenLM" models** for finance document
understanding, spend classification, fraud detection and workflow execution. Extracts and
validates invoice data, matches POs, predicts GL codes for non-PO invoices, moves invoices
from capture to "ok-to-pay" without human touch. Duplicate detection via deep models that
flag high-risk invoices at ingestion against previously processed ones. Audits every
expense report at submission, before payment. AI Agent Studio for custom agents.

**Distribution [S]** AWS Marketplace. Expense audit controls pushed into Workday.

**Customers [V]** Airbus, Databricks, Georgetown University, Honeywell, Takeda.

**Claimed impact [V]** Up to 80% AP automation, up to 50% finance opex reduction.

**Pricing [S]** No public tiers. Vendr transaction data: **~$26k/yr average, ~$47k max.**

**Injection posture** None stated.

**Relevance** The closest functional analogue to PRAETOR's rules baseline plus
adjudicator — duplicate detection, anomaly audit, autonomous resolution. Their duplicate
model does what `DUPLICATE_INVOICE` does, at enterprise scale, with named customers.
Do not claim novelty on detection.

## Stampli

**Scale [V]** 2M+ invoices/month, **1,700+ customers**, **$105B annual invoice value**.

**Pricing [S]** Quote-based, ~$250–$1,500/month depending on volume and modules.

## Tipalti

**Pricing [S]** From ~$99/month; full deployments with global payments $1,500–$5,000/mo.
Platform ~$24k/yr core, scaling to **$100k–$300k/yr** enterprise with global payments.

## Ramp

**Model [S]** Bundles a free AP tier with its corporate card. Monetises on interchange —
structurally different, and it means AP automation is a loss-leader for them.

## Others in the tier

Bill.com, HighRadius, Coupa, Basware, Medius, Yooz, Stampli. Mostly OCR + rules on money
fields, AI on classification and matching. All adding AI now.

---

# 4. Payment fraud / vendor verification

**This sector is not a competitor. Under Corroboration Gating each of these is a
corroboration source — an external, attacker-independent attestation. Frame them as
integrations, not rivals.**

## Trustpair

**Mechanism [S]** In-network database lookup **plus out-of-network validation via
micro-payment** — the vendor proves control of the account. Issues reusable **Bank
Account Certificates** as proof of validation.

**Architecture [S]** Sits inside the procure-to-pay workflow, native ERP and procurement
integration. Applies validation rules and fraud logic within ERP/treasury environments.
**Continuous monitoring**, not point-in-time.

**Coverage [V]** 190+ countries; named coverage includes US, China, France, UK, Italy,
Netherlands, Belgium, Brazil, India, South Africa, Mexico, Poland, Sweden, most of
Eastern Europe.

**Scale [S]** **400+ enterprise customers.** Raised **$25.4M**. Nacha preferred partner.

**Why it matters to us.** The micro-payment is a genuinely attacker-independent
attestation that the account holder controls the account. PRAETOR's Time axis ("have we
paid this before") is a *weak proxy* for what Trustpair establishes properly. **This is
the strongest available fourth axis.**

## nsKnox

**Mechanism [S]** PaymentKnox. High-assurance bank account ownership validation plus
sanctions screening. Same in-network + out-of-network micro-payment pattern. Positioned
from a cyber-security angle. Best suited to enterprise/multinational.

**Funding [S]** **$32M over 7 rounds**; last was a $17M Series B, Jan 2023.

## Eftsure

**Mechanism [S]** Sits between the AP system and the bank, verifying every payment
destination **at the moment of payment**.

## apexanalytix

Vendor verification plus cross-customer supplier intelligence. Publishes research on
AI-driven supplier payment fraud. Their cross-customer data network is the thing PRAETOR
explicitly gave up via tenant isolation (ADR #7).

### What none of them do

**They guard exactly one field.** Nothing here stops an agent being talked into resolving
a tax discrepancy, waving through a duplicate, or accepting a fabricated authority claim.

---

# 5. Document extraction / IDP — the front-door layer

## Rossum — *acquired by Coupa*

**What it is [V]** AI-first transactional document processing. Template-free.

**Architecture [V]** **Rossum Aurora**, a proprietary "transactional LLM" trained on
millions of transactional documents. Language-agnostic, 100% template-free, continuously
learning per customer. "Enterprise-grade safety built in."

**Training data [V]** One of the largest transactional document sets in the world —
including **DocILE, which Rossum publishes and PRAETOR uses.**

**Corporate [S]** **Acquired by Coupa** to accelerate end-to-end autonomous spend
management.

**Relevance** The publisher of our dataset is now inside a major spend platform, running
a production LLM trained on it. Worth stating plainly in prior art.

## Google Cloud Document AI

**Invoice Parser [P]** Returns entities with `type`, `mentionText`, and
`pageAnchor.boundingPoly.normalizedVertices` — normalised 0–1 coordinates. **This is the
same shape `praetor/docile_adapter.py` already consumes.**

**Pricing [S]** **$0.01/page** ($0.10 per 10 pages). Sync requests max 10 pages; batch to
200 pages.

**Accuracy caveat [V, vendor-run]** On RD-TableBench, **Google Document AI scores 64.6%**
vs Reducto 90.2%, Azure Document Intelligence 82.7%, AWS Textract 80.9%. **This benchmark
is run by Reducto**, who win it. It measures complex *tables*, not invoice header fields,
and Document AI has a purpose-built Invoice Parser that this benchmark does not exercise.
Still — validate on our own documents before publishing any accuracy claim.

## Reducto

**Architecture [V]** Hybrid vision-first pipeline: computer vision + OCR + VLM + "Agentic
OCR". Preserves layout, produces LLM-ready chunks with **per-value citations**. Full
lifecycle: Parse, Extract, Classify, Split, Edit. 100+ languages, 30+ file types.

**Scale [V]** 4 billion+ pages processed. Cloud, VPC or on-prem. HIPAA with BAA, Zero Data
Retention on Growth/Enterprise.

**Note** "Per-value citations" is the same idea as span provenance. Worth reading.

## LlamaParse

**Pricing [S]** Credit-based; Fast mode 1 credit/page, Agentic Plus **45 credits/page** —
a 45× spread on the same page.

## Azure Document Intelligence · AWS Textract

Budget options for high-volume OCR and standard forms **[S]**.

## Instabase

Enterprise IDP. Could not establish pricing or architecture detail from public sources.

---

# 6. AI security — architectural prevention (PRAETOR's family)

**This sector is astonishingly thin, and that is the most important finding in this
document.**

## CaMeL — Google DeepMind

**Paper [P]** *Defeating Prompt Injections by Design*, arXiv 2503.18813 (Google, Google
DeepMind, ETH Zurich).

**Code [P]** `github.com/google-research/camel-prompt-injection`

**Architecture [P]** Privileged LLM converts the user command into a plan in a Python-like
language. A custom interpreter executes it, tracking data provenance and enforcing
capability policy before each tool call. A quarantined LLM processes untrusted data with
no tool access.

**Google's own disclaimer [P]** *"A research artifact released to reproduce the results in
the paper... the interpreter implementation likely contains bugs and may not be fully
secure... this is not a Google product with planned support or maintenance."*

**Named limitations [P]** (from *The Attacker Moves Second*): assumes the initial user
query is benign · cannot protect against text-to-text attacks · requires hand-coded
security policies.

## Dromedary — Microsoft

**Code [P]** `github.com/microsoft/dromedary` — a replication of CaMeL.

**Architecture [P]** **Code-Then-Execute.** Privileged LLM agent (LangGraph + MCP tools)
plans in Python; a custom Python interpreter executes it while tracking:
1. **Data provenance** — which tool the data came from, where it goes
2. **Data labels** — how sensitive it is

A `query_ai_assistant` tool queries a **quarantined LLM** with no tool access, for string
manipulation only. Policy engine is hardcoded Python today; the author wants **OPA/Rego**.
MCP for tool definitions.

**Their banner [P]** *"NOT TO BE USED IN PRODUCTION."*

**Missing [P]** Full RBAC; a performant interpreter (author suggests rewriting in Rust).

**The policy refusal, verbatim [P]**
```
🚫 POLICY VIOLATION: Cannot send email to address from untrusted source
'get_received_emails'. Use search_contacts_by_name or search_contacts_by_email.
```

**Relevance — read this twice.** That refusal is *structurally identical* to PRAETOR's
`TAINTED_ACCOUNT_NOT_IN_MASTER`. Same mechanism, different domain. We are unambiguously in
this family and can cite Microsoft as a peer implementation.

**And here is our differentiator.** Dromedary's policy says *"use the trusted tool
instead"* — it has a trusted alternative source (`search_contacts_by_name`). **Our domain
has no trusted alternative.** There is no oracle for "which account should this invoice be
paid to." That is the harder case, and it is exactly why corroboration is needed rather
than source-swapping.

## AuthGraph — current SOTA

**Paper [S]** *Aligning Provenance with Authorization: A Dual-Graph Defense for LLM
Agents*, arXiv 2605.26497, 26 May 2026.

**Architecture [S]** Two graphs: an *injected reasoning graph* from the actual execution
trajectory, and an *authorization graph* derived from the user's intent **in an isolated
clean context that is information-theoretically impossible to influence by injection**. A
graph alignment checker structurally compares them at tool-level and
parameter-source-level.

**Results [S]** AgentDojo 40% → **1%** ASR at 76% task completion (GPT-4o); AgentDyn 39% →
2% at 51% utility. Outperforms CaMeL, DRIFT, Progent.

**Relevance** Beats our foundation, and **still anchors on user intent and still scores
tool calls.** Both of our structural bottlenecks apply to the current state of the art.

## RTBAS, FIDES, Progent, FORGE

Cited in the literature as the same family. No prominent public implementations found.

## Warden

`github.com/VictoriousAttitude/warden` — "runtime trust layer for LLM agents:
information-flow control and capability enforcement at the tool boundary, on a
content-addressed provenance graph." **Zero stars.** Nobody is using it.

### Sector conclusion

**Two implementations of this approach exist worldwide — one from Google, one from
Microsoft — and both carry explicit "not for production" warnings.** Everything shipping
in production is detection. If PRAETOR works end to end in a real business workflow, it is
one of very few working systems in this family.

---

# 7. AI security — detection and guardrails

## Lakera Guard → Check Point

**Corporate [S]** Acquired by **Check Point, September 2025**. Zurich research team
continues under Check Point; new sales route through Check Point procurement.

**Architecture [S]** Sits between users and the LLM. Every input and output passes the
detection engine before reaching the model. Scans fetched content, attachments and URLs
for embedded instructions — including hidden HTML, PDFs, uncommon languages. "Prompt
Defense" guardrail scans user inputs *and retrieved/reference documents*.

**Training [S]** Proprietary detectors plus rules, trained on large-scale adversarial data
from red-teaming and the **Gandalf** challenge. **100,000+ new attacks analysed daily.**

**Claims [V]** **98%+ detection · <50ms latency · <0.5% false positives · 100+ languages.**

**Their own stated limitation [S]** Approaches that use one LLM to detect adversarial
behaviour in another *"inherit the exact same vulnerabilities."*

**How to argue against it — this is the important part.** Do **not** dispute the 98%. It
is measured on their distribution, which is Gandalf-derived and therefore
adversarial-looking. Our 12 successful payloads are indistinguishable from legitimate
invoice text. **The argument is about false positives, not accuracy:** a filter that
caught *"please note our updated banking details"* would have to flag genuine remittance
notices, and their 0.5% FPR is measured on general traffic, not invoice footers. Their
precision claim and our evasion claim are **compatible**.

## Google Model Armor

**What it is [S]** Identifies and blocks prompt injection and jailbreaking. Protects any
LLM — Gemini, OpenAI, Anthropic, Llama — via a REST API, independent of cloud/infra. Also
does sensitive-data de-identification and screens the first 40 URLs per request.

**Availability [S]** GA. Enables on an Agent Gateway resource. Multiple regions with EU
data residency.

**Pricing [S]** **Free to 2M tokens/month**, then $0.10 per million.

**Relevance** The head-to-head experiment. Our 20 payloads cost ₹0. `DECISIONS.md §1`
currently *asserts* that a filter would fail; this converts it to a measurement, using the
filter product of the company running the hackathon.

## The funded field [S]

Protect AI ($60M Series B, → Palo Alto Networks) · Prompt Security · Lasso Security ·
CalypsoAI · Robust Intelligence (→ Cisco) · HiddenLayer · **Archestra.AI ($10M seed)** —
"a secure middle layer so AI agents can access sensitive company data without bypassing
policy; checks identity and policy, logs access, reduces prompt-injection and exfiltration
risk." Archestra is the closest *funded* company to our architectural approach.

**Nearly all of this sector is guardrails and input scanners — i.e. detection.**

---

# 8. Enterprise agent security platforms

## Zenity

**Positioning [V]** "Industry's first AI security platform for autonomous agents." Governs
AI decisions before they become enterprise actions, including long-horizon agents.

**Architecture [V]** Security at the **decision layer** — evaluates every AI action before
it becomes an enterprise action. Rather than inspecting prompts, examines the **full
execution path**: tool calls, memory access, data usage, control flow. Unifies posture,
runtime behaviour and threat signals into real-time risk. Products: **Observe** (AISPM),
**Govern**, **Defend** (AIDR). Adds Exposure Management and Runtime Boundaries.

**Coverage [V]** SaaS, home-grown agentic platforms, endpoint. AIDR monitors cloud agent
execution step by step, mapped to **OWASP and MITRE ATLAS**, blocks unsafe actions in real
time, reconstructs the decision chain, uses "Guardian Agents" to learn from investigations.

**Relevance** The closest *commercial* analogue to PRAETOR's gate. Still tool-call
oriented. Enterprise platform play, not a domain product.

## Uber ADR — the only production system found

**Code [P]** `github.com/uber/ADR` · 1.5k stars · Apache 2.0
**Paper [P]** *ADR: An Agentic Detection System for Enterprise Agentic AI Security*,
**MLSys 2026**. **Deployed in production at Uber.**

**Five components [P]**
1. **Discovery** — inventories AI apps, CLI agents, IDE extensions, model runtimes, MCP
   servers on endpoints
2. **Observability** — captures agent intent, tool use, execution traces across 7+ AI
   coding tools on macOS/Linux/Windows
3. **ADR-Bench** — **303 tasks, 133 MCP servers, all 17 agent attack techniques**; vendors
   AgentDojo (MIT)
4. **Detection** — two-tier: high-recall triage plus deeper agentic reasoning on suspicious
   sessions. Dual-agent detector, needs `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
5. **Prevention** — *"not included in the current open-source release. Stay tuned."*

**Two observations that matter.** It targets **employee-facing** agents (Cursor, Claude
Code, Codex) and customer-facing support agents — **not document pipelines**. And what
Uber ships and open-sources is **detection**; the prevention module is withheld. Their
detector is an LLM judging another LLM — the pattern Lakera's own docs warn inherits the
same vulnerabilities.

---

# 9. Open source and research codebases

| Repo | Stars | Status | Note |
|---|---:|---|---|
| `NVIDIA/SkillSpector` | 15.0k | active | Scans agent skills for injection, exfiltration, supply-chain risk. Install-time, not runtime |
| `superagent-ai/superagent` | 6.7k | active | Injection / data-leak / harmful-output protection, embedded in-app |
| `Tencent/AI-Infra-Guard` | 6.0k | active | Full-stack AI red-teaming: agent scan, skills scan, MCP scan, jailbreak eval |
| `protectai/llm-guard` | 3.2k | **ARCHIVED** | "The Security Toolkit for LLM Interactions" |
| `microsoft/AI-Red-Teaming-Playground-Labs` | 2.0k | active | Training labs + infra |
| `uber/ADR` | 1.5k | active | Production at Uber, MLSys 2026 |
| `protectai/rebuff` | 1.5k | **ARCHIVED** | "LLM Prompt Injection Detector" |
| `utkusen/promptmap` | 1.3k | active | Security scanner for custom LLM apps |
| `luckyPipewrench/pipelock` | 815 | active | AI agent firewall; **"mediator-signed action receipts: verifiable audit evidence from outside the agent"** — directly relevant to a provenance-receipt feature |
| `ethz-spylab/agentdojo` | 772 | active | The benchmark everyone reports on |
| `microsoft/dromedary` | — | active | **Read properly.** Closest architectural sibling |
| `google-research/camel-prompt-injection` | — | research artifact | The foundation |
| `VictoriousAttitude/warden` | 0 | active | IFC + capability at the tool boundary |

**The archived-projects signal.** Both flagship open-source *detection* projects —
`llm-guard` (3.2k) and `rebuff` (1.5k) — are archived. Protect AI was acquired by Palo
Alto, which may explain it, but the OSS detection ecosystem is not thriving.

---

# 10. Benchmarks and datasets

| Name | ID | What it measures | Fit to PRAETOR |
|---|---|---|---|
| **AgentDojo** | arXiv 2406.13352 | 97 tasks / 629 security cases across banking, Slack, travel, workspace. Did the agent execute the attacker's tool sequence | **No** — scores tool calls. Its canonical attack (`ImportantInstructionsAttack`) is delimiter-wrapped and addresses the model by name, i.e. our *resisted* class |
| **BIPIA** | arXiv 2312.14197, KDD'25 | Email/Web/Table QA, summarisation, Code QA. 30 text + 20 code attack types. 86,250 test prompts | **No** — no extraction task, no privileged field. Nearest category, *Scams & Fraud*, is about emitting scam content to a reader |
| **InjecAgent** | arXiv 2403.02691 | 1,054 cases, 17 user tools, 62 attacker tools. Direct harm + data stealing | **No** — attacker instruction is a free-standing imperative; the sink is a tool |
| **ADR-Bench** | uber/ADR | 303 tasks, 133 MCP servers, 17 attack techniques | **No** — enterprise agent behaviour |
| **RD-TableBench** | Reducto | 1,000 complex tables | Extraction accuracy only. **Vendor-run** |
| **DocILE** | Rossum | Transactional document annotations | Used by PRAETOR. Note Rossum trained Aurora on it and is now inside Coupa |

**Verified 27 Aug 2026: no published benchmark measures value-substitution injection in a
document-extraction pipeline.** Checked BIPIA, AgentDojo, InjecAgent against primary
sources, plus the RAG/QA/tool-selection benchmark landscape. The gap is real.

---

# 11. Key papers

**Tier 1**
- **CaMeL** · arXiv 2503.18813 · the foundation. Read the limitations section
- **The Attacker Moves Second** · arXiv 2510.09023 · USENIX Security '26 · **the one that
  can hurt us.** 12 defences, all broken, >90% ASR on most, 100% human red-team. Names
  CaMeL explicitly
- **AuthGraph** · arXiv 2605.26497 · current SOTA
- **Agents Rule of Two** · Meta AI, Nov 2025 (blog) · at most two of {untrusted input,
  sensitive data, state change}. **PRAETOR is [AB]** — the agent can only propose

**Tier 2**
RTBAS `2502.08966` · Granularity Mismatch / argument-level provenance `2605.11039`
(describes a "grounder" that maps values to source spans — this is `resolver.py`) ·
Meta SecAlign `2507.02735` · Adaptive Attacks Break Defenses `2503.00061` · MELON
`2502.05174` · IPIGuard `2508.15310` · PromptArmor `2507.15219` · ARGUS `2605.03378` ·
Ghost in the Agent `2604.23374` · EchoLeak `2509.10540` (first real-world zero-click
exploit) · Learning to Inject `2602.05746` · CSA *Indirect Prompt Injection in the Wild*
(Apr 2026)

---

# 12. Synthesis — where PRAETOR actually sits

## Genuinely contested (do not claim novelty)

- **Rules, anomaly detection, duplicate detection** — AppZen has 200+ models and Airbus as
  a customer
- **Three-way matching / PO reconciliation** — Oracle ships it; standard since the 1970s
- **Vendor master verification and exception escalation** — Microsoft Payflow does exactly
  this
- **Approval workflow on bank-detail changes** — Dynamics ships it
- **Account ownership verification** — Trustpair does it properly with micro-payments
- **Reference-only extraction** — CaMeL, Dromedary. Cite them

## Genuinely uncontested

1. **The extraction→policy boundary in a document pipeline.** Every ERP agent extracts
   fields with a model and then applies policy. **None has publicly addressed the fact
   that the extracting model can be made to author the value.**
2. **The empirical finding.** Which injection techniques beat a document-extraction prompt,
   and the total semantic/syntactic split. Nobody has published this.
3. **The benchmark gap.** No benchmark measures value substitution in document extraction.
4. **The two structural bottlenecks.** Every defence found — CaMeL, Dromedary, AuthGraph,
   Zenity, ADR, Warden — puts policy on **tool calls** and anchors on **user intent**.
   Neither exists in a batch document pipeline.

## The three threats, ranked

1. **Microsoft Payflow Agent.** Already ships the policy layer. If Microsoft connects
   Dromedary to Payflow, the gap closes and PRAETOR's contribution is absorbed.
2. **Commoditisation.** Oracle and SAP ship fraud checks and PO matching. Anything we
   claim in that territory is competing with them.
3. **No confirmed incident.** The threat is anticipated, not observed. A hostile judge or
   investor can say "this hasn't happened yet."

## The three strongest positions

1. **Vic.ai gates autonomy on model confidence; we gate on independent corroboration.**
   Confidence is what an injection is best at defeating.
2. **Filtering fails on false positives, not accuracy.** Lakera's 98% and our evasion claim
   are compatible, and that is a much harder argument to dismiss.
3. **Trustpair is an axis, not an enemy.** Reframing the strongest incumbent as a
   corroboration source converts our most-conceded weakness into an integration point.

---

## Gaps still open in this sweep

- Instabase architecture and pricing — not established
- Frontend/backend stacks for private vendors — almost entirely non-public
- SAP and Oracle injection posture — no public statement found either way
- User complaints / churn signals from review sites — not gathered
- Regulatory angle (SOX attestation, EU AI Act on autonomous payment decisions) — not
  researched; likely matters for "who pays for the failure"

---

# 13. Reverse engineering — what the code actually does

Read 27 Aug 2026. Everything in this section is **[P] primary**: I read the source, not
the marketing. File paths are given so it can be re-checked.

The two reference implementations of the state-of-the-art defence are open source:
Google's CaMeL and Microsoft's Dromedary. Both are cited constantly and neither is
usually read. Here is what they actually do.

## 13.1 Dromedary (Microsoft) — provenance DAG plus policy

### The value wrapper — `src/dromedary/provenance_graph.py`

```python
@dataclass
class CapabilityValue:
    node_id: int      # pointer into the provenance graph
    value: Any        # the value itself, unconstrained
```

Every value in the interpreter is a `CapabilityValue`: the value plus a node id. The
graph holds `nodes` (values), `sources` and `edges` (dependencies).

`SourceType` is one of `USER`, `TOOL`, `SYSTEM`, `INVOCATION`.

Values are minted by `ProvenanceTracker`:

```python
def from_tool(self, value, tool_name, dependencies=None) -> CapabilityValue:
    source = Source(type=SourceType.TOOL, identifier=tool_name)
    node_id = self.graph.add_node(value, source, dependency_ids=[...])
    return CapabilityValue(node_id=node_id, value=value)
```

**Note what this does not do.** `from_tool` accepts *whatever the tool returned*. There is
no constraint on the value. A compromised tool — or the quarantined LLM reached through
`query_ai_assistant` — returns an arbitrary string and Dromedary faithfully records that
it came from an untrusted source. **The value is labelled, never bounded.**

### The enforcement — `src/dromedary/policy/loader.py::EmailPolicy._check_recipient_provenance`

```python
untrusted_tools = set(self.config.get("untrusted_provenance_sources", []))
ancestors, _ = provenance_graph.get_ancestors_subgraph([recipients_cap.node_id])
for node_id in ancestors:
    source = provenance_graph.sources.get(node_id)
    if source and source.type.value == "tool":
        if source.identifier in untrusted_tools:
            violations.append("Cannot send email to address from untrusted source ...")
            break
```

That is the whole mechanism: walk the ancestors of the value entering the sink, and refuse
if any ancestor came from a tool named on a **hand-maintained config blocklist**.

### Five things worth knowing about it

1. **It is a blocklist, so it fails open.** `untrusted_provenance_sources` is a list of
   tool names. A tool nobody has added is implicitly trusted.
2. **Exactly one tool has provenance enforcement.** `EmailPolicy` checks it.
   `CalendarPolicy` and `FilePolicy` do not — they are pure argument validation. Coverage
   is 1 of 6 policed tools.
3. **Transitive taint, no declassification.** Any untrusted ancestor poisons the value
   permanently. There is no way to say "derived from untrusted data, since validated."
4. **The `.rego` files appear to be unused.** `policies/*.rego` exist, but
   `policy/engine.py` loads a YAML config and dispatches to Python `Policy` classes. No
   OPA call is made on this path. The README's "I would like to use Rego" is still the
   state of things.
5. **The sensitivity check is substring matching.** `FilePolicy` flags content containing
   any of `["confidential","secret","private","password","key"]` via
   `pattern in lower_content`. `"key"` matches *monkey*, *keyboard*, *turkey*.

### And the policy the demo actually relies on — `policies/email_policy.rego`

```rego
allowed_recipients := {
    "bob.wilson@techcorp.com",
    "alice.cooper@clientcorp.com",
    "mossaka@bluesparrowtech.com",
    "john.doe@bluesparrowtech.com",
    "jane.smith@bluesparrowtech.com",
}
```

**A static allowlist of five literal email addresses.** When provenance labelling cannot
decide, the fallback is an enumerated list of permitted sinks.

## 13.2 CaMeL (Google) — an IFC lattice

### `src/camel/capabilities/capabilities.py`

```python
@dataclasses.dataclass(frozen=True)
class Capabilities:
    sources_set: frozenset[sources.Source]   # integrity: where did this come from
    readers_set: readers.Readers             # confidentiality: who may read it
    other_metadata: dict[str, Any]
```

### `src/camel/capabilities/sources.py`

```python
class SourceEnum(Enum):
    CaMeL, User, Assistant, TrustedToolSource

@dataclasses.dataclass(frozen=True)
class Tool:
    tool_name: str
    inner_sources: frozenset[str | SourceEnum]   # e.g. which email addresses contributed
```

This is a classical two-dimensional information-flow label — integrity × confidentiality —
propagated by set union rather than graph traversal. `Tool.inner_sources` is genuinely
finer-grained than Dromedary: CaMeL can say *"from tool `read_email`, specifically from
sender X"*, which supports per-entity policy.

**But the same structural fact holds.** `Capabilities` wraps a value with labels. Nothing
constrains what the value may be.

## 13.3 The decisive comparison

| | CaMeL (Google) | Dromedary (Microsoft) | PRAETOR |
|---|---|---|---|
| Unit | `Capabilities(sources_set, readers_set)` | `CapabilityValue(node_id, value)` | `Field(value, Provenance(doc_hash, span_id, tainted))` |
| Model | IFC lattice, set union | provenance DAG, ancestry walk | grounding + policy |
| **May the model author the value?** | **Yes** | **Yes** | **No — `resolve()` rejects anything that is not a span reference** |
| Trust decision | is the source label acceptable | is any ancestor on the untrusted blocklist | is the value corroborated outside the document |
| Default | configured lattice | **fail-open** (unlisted tool is trusted) | **fail-closed** (unknown account escalates) |
| Declassification | policy-defined | none | human approval |
| Coverage | per-tool policy | **1 of 6 policed tools** | every privileged field |
| Status | *"not a Google product... may not be fully secure"* | *"NOT TO BE USED IN PRODUCTION"* | deployed |

## 13.4 The finding

> **Both reference implementations label a value with where it came from, then ask a
> policy to decide. Neither constrains what the value can be.**
>
> In both, a compromised quarantined LLM returns an arbitrary string, the system correctly
> records that it came from an untrusted source, and the decision then falls to a
> hand-maintained list — a blocklist of tool names in Dromedary, an allowlist of five
> email addresses in its demo policy.

This is bottleneck 3 observed in production code rather than argued from theory. **A label
tells you the origin. It cannot tell you whether anything else agrees.** When every input
is untrusted — which is the normal case for a document pipeline — the label is constant
and therefore carries no information, and the system falls back to enumerating permitted
values by hand.

**PRAETOR's resolver does the thing neither does:** it refuses to *construct* a value that
is not a reference into the immutable source document. Not "this value is tainted" but
"this is not a value I will build." That is a different operation, verified absent from
both reference implementations.

## 13.5 What this licenses us to say, and what it does not

**Can say, and can prove by citing file and line:**
- The two reference implementations track provenance and do not ground values
- Dromedary's provenance enforcement covers one tool and fails open on unlisted sources
- Its fallback when labels cannot decide is a static allowlist
- Its sensitivity check is substring matching with the classic false-positive flaw

**Must not say:**
- That CaMeL or Dromedary are *bad*. Both are explicitly research artifacts and say so.
  Judging a research demo by production standards is unfair and a judge will notice
- That grounding is *better* than IFC labelling in general. It is better *for a sink whose
  legitimate values are enumerable from a trusted record*, which is our domain and not
  theirs
- That we invented grounding. arXiv 2605.11039 calls it a "grounder"

**The fair claim:** *the reference implementations label; we ground; here is the code for
all three.*
