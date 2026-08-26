# Devpost submission pack

Paste-ready text for each field. Everything here matches what the repository actually
does as of the current commit — if you change a number, change it in
[FINDINGS.md](../FINDINGS.md) first and let it flow out from there.

**Checklist before you submit**

- [ ] Repo shared with `testing@devpost.com` **and** `cloudhackathons@google.com`
      — the rules allow a private repo if both are granted access, so invite them
      through the GitHub web UI (email invites work there; the API needs usernames)
- [x] **Google Cloud infrastructure** — deployed on Cloud Run (`asia-south1`) with
      state in Cloud Firestore. Show both consoles in the video.
- [ ] `docs/architecture.png` uploaded — this is a **required** file upload
- [ ] Demo video uploaded, under 4 minutes, public link
- [ ] Blog post published, link added
- [ ] Social post published with **#AllThingsAgenticHackathon**, link added
- [ ] Submitter Type = **Individual/Team**, not Organization
- [ ] Project start date inside **3–31 Aug**
- [ ] Track = **Taskmaster**

---

## Project name

```
PRAETOR
```

## Elevator pitch (one line)

```
An accounts-payable agent that resolves invoice exceptions on its own — and cannot be hijacked by the document it is reading.
```

## Model version (state it exactly; never the -latest alias)

```
gemini-3.5-flash-lite (primary), falling back to gemini-3.5-flash.
Gemma 3 1b runs on-device via Ollama as the last link in the chain.
```

---

## Inspiration

```
We started with a measurement rather than an architecture. Take an ordinary invoice
extraction prompt, hide an instruction inside the document, and see how often the model
hands back an attacker's bank account instead of the supplier's. We ran twenty
documented indirect-injection techniques. Twelve worked.

The number wasn't the finding. The split was. Every payload that worked reads like
ordinary business correspondence — a remittance notice, a fabricated approval reference,
an instruction tucked into a field label. Every payload that failed looks like an attack:
"ignore previous instructions", hidden text, base64, delimiter escapes.

The model resists what looks like an attack and obeys what looks like an invoice. That
kills the filter approach, because a prompt-injection classifier is trained on
adversarial-looking text — it catches the ones that were already failing and misses the
ones that work. "Please note our updated banking details" is not a jailbreak. It is a
sentence that appears on real invoices every day.
```

## What it does

```
PRAETOR processes invoices end to end for outsourced accounts-payable processors, who
bill $2.50–$5.00 per invoice and lose margin on every exception a human has to touch.

It learns what each supplier's invoices normally look like from their own past invoices,
passes clean ones straight through, and hands a person one screen for the odd ones — with
the evidence attached.

On 350 invoices, 303 never reach a human: 86.6% autonomous. The rules baseline flags 65
exceptions; the agent clears 18 of them correctly, at 1.000 precision, with zero wrong
resolutions.

The part that matters is what happens when the document fights back. Two invoices talked
the agent into the wrong answer — one with a convincing remittance notice, one with a
fabricated approval ticket. Deterministic code overruled both.
```

## How we built it

```
The principle is that the model handles references, never values.

1. The document is stored immutably and hashed. Its annotations become numbered spans.
2. A quarantined reader — no tools, no memory, no network beyond its own model call —
   sees the spans and may answer only with span IDs. It runs on Gemma 3 1b locally, or
   Gemini 3.5 Flash-Lite.
3. A resolver with no LLM in it looks each ID up in the immutable document and rejects
   anything that is not a real span. A fully compromised reader can point at the wrong
   span; it cannot introduce one.
4. Every resolved value carries its doc_hash, its span_id, and a TAINTED flag.
5. A 118-line rules baseline — written before any agent code, deliberately — flags
   deviations from the supplier's own pattern. It gets F1 0.874 and names the right
   reason on 100% of catches, so the agent does not detect. It adjudicates.
6. The exception agent reads findings and context, never raw document text, and its
   answer is advisory.
7. A policy gate with no LLM has the last word: a tainted account not in the vendor
   master cannot be paid; an authorisation the document claims for itself counts only if
   it names a reference in the buyer's own register; one client's vendor master can never
   vouch for another's invoice. The agent's ceiling is propose_pay.
8. A human approves — one act that is both the SOX segregation-of-duties control and the
   declassification step.

115 tests hold those claims. Approving as an agent raises PermissionError, in the tests
and in the live queue.
```

## Challenges we ran into

```
The honest one: our own measurement didn't reproduce. We had reported the rules baseline
at recall 1.000 / F1 0.865. Re-running it gave different numbers, and the cause was a
results file that had been overwritten by a run against a smaller corpus — 42 exceptions
being scored against 350 invoices of ground truth. The real figures are precision 0.800,
recall 0.963, F1 0.874. The same stale file had been feeding the review dashboard, which
was showing no flag reason on 23 of its 65 rows.

The second: our first adjudication run had one wrong resolution, and it was caused by a
successful prompt injection. A fabricated approval ticket — "AP-88213, approved by
Finance Director" — persuaded the agent to resolve a genuine tax-rate exception. It could
not move the money, because a bank account is privileged. It did move the decision,
because a tax rate is not.

We wrote that up as an open limitation and named the fix, then built it. An authorisation
a document claims for itself now counts only if it matches the buyer's purchase-order
register. That wrong resolution is gone and precision went to 1.000.

The third was smaller and more instructive than it looks. Our local fallback model kept
returning the answer schema back to us verbatim, which is invalid JSON, so it failed
closed and silently adjudicated nothing. A worked example in the prompt fixed it.
```

## Accomplishments that we're proud of

```
That the agent was fooled twice and the outcome was correct both times. We did not have
to make the agent un-foolable — we had to make being fooled not matter.

And that the whole thing reproduces from a clean clone with no API key, no cloud account
and no billing: `make install && make demo` gives 115 passing tests, the rules baseline,
and the full review queue.
```

## What we learned

```
That the defence you reach for first is the wrong one. Filters are trained on text that
looks adversarial, and the attacks that actually work don't look adversarial at all.

That writing the dumb baseline first was the highest-leverage decision we made. 118 lines
of Python already catch 96% of deviations and name the right reason every time. That told
us on day two that the agent's job was adjudication, not detection — which is a different
product from the one we would otherwise have built.

And that a measurement you can't reproduce is worse than no measurement.
```

## What's next for PRAETOR

```
Deploy the service itself to Cloud Run — state already runs on Cloud Firestore — and
report throughput, peak concurrency and real dollar cost from a Pub/Sub fan-out run.

Close the remaining gap in the authority rule: a document that is persuasive while naming
no checkable reference at all is still not caught.

Replace our hand-authored payload taxonomy with an indirect-injection benchmark we did
not write, and report that as the headline number.
```

## Built with

```
python, google-gemini, gemma, ollama, google-genai-sdk, google-cloud-firestore, sqlite, opentelemetry
```

---

## Testing instructions (scored, publicly visible)

```
Requires Python 3.11–3.13 (not 3.14) and make. No API key, no cloud account, no billing.

    git clone https://github.com/adityasinghin01-hash/praetor.git
    cd praetor
    make install
    make demo

make demo runs in about ten seconds, makes no network calls, and costs nothing. Expect
39 passing tests, the rules baseline at precision 0.800 / recall 0.963 / F1 0.874, and
dashboard/index.html — the queue a human actually works.

To prove the corpus is reproducible rather than committed-and-trusted:

    make verify

This regenerates all 350 invoices from a fixed seed. The result is byte-identical to the
committed corpus, so git status stays clean and every downstream number lands on the same
values.

For the queue with working approvals:

    make serve            # http://127.0.0.1:8000

Every flagged value shows its provenance — TAINTED, the span it came from, the hash of
the document it came from. The approve button calls the real praetor.gate.approve().
Type agent:exception_resolver into the "approve as" box to watch the real PermissionError
come back to the browser.

The two targets that call the Gemini API are make attacks and make adjudicate. Both need
GOOGLE_API_KEY, and both are capped by praetor/costguard.py, which prices each call
against Google's published rates and raises before the call that would cross a ceiling.

Every number we publish is reproducible — see FINDINGS.md, which also records the two
measurements that had to be corrected.
```

---

## Links

| Field | Value |
|---|---|
| Working project URL | `https://praetor-836128159455.asia-south1.run.app` |
| Repository | `https://github.com/adityasinghin01-hash/praetor` |
| Architecture diagram | upload `docs/architecture.png` |
| Blog post | *(paste published URL)* |
| Social post | *(paste published URL)* |
| Demo video | *(paste public video URL)* |
