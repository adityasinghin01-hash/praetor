# Demo video — 200 seconds

Cap is 240s and **only the first four minutes are judged**, so this runs to 200 and
leaves headroom. Narration is ~510 words, which is 155 wpm — an unhurried pace. Do not
speed up to fit more in.

The architecture diagram is a separate required upload. **It gets no video time.**

## Before you record

- Pre-run `make demo`. Never run `make adjudicate` live: the free tier is 20 calls per
  day per model and it will exhaust partway.
- **`source .venv/bin/activate` in the recording terminal**, and paste the beat-3 command
  once before you roll. Bare `python3` on this Mac is 3.14, which the project does not
  use — the one live command in the demo is the one that breaks without this.
- Start the queue with `make serve` and leave it on `http://127.0.0.1:8000`. Beat 6
  approves for real, so **clear prior approvals before you record** — otherwise the row
  you want to approve already shows as approved. Approvals live in SQLite now, not
  JSONL (`docs/DECISIONS.md` §6), so it is:

  ```bash
  .venv/bin/python -c "import sys;sys.path.insert(0,'.');from praetor import store;\
c=store.connect();c.execute('DELETE FROM approvals');c.commit()"
  ```
- **Know the queue's controls before you roll** — they carry beats 4, 5 and 6 now:
  `/` focuses search · `j`/`k` move · <kbd>enter</kbd> opens the document as the reader
  saw it · <kbd>u</kbd> opens the audit trail · <kbd>a</kbd> approves the selected row ·
  `?` lists them. The **show** and **finding** chips filter the queue in one click.
  All of it works with no server, so a dropped connection mid-take costs you only the
  document viewer and the approve button.
- Have `ollama serve` running with `gemma3:1b` pulled. The reader beat is live, free and
  has no quota — it is the only thing worth risking on camera.
- Terminal at ~18pt, dark theme, window 1600×900. The dashboard and terminal share a
  palette, so cuts between them should feel like one product.
- Two windows only: terminal and the browser. No IDE, no tab bar full of tabs.
- Record at 1080p minimum. Screen text is the whole demo.

---

## 1 · Cold open — 0:00–0:20 (20s)

**On screen:** the queue at `http://127.0.0.1:8000`, stat cards only, then a slow scroll
into the table.

> Three hundred and fifty invoices went through this system. Forty-seven reached a human.
> That's eighty-six point six percent handled with nobody looking at them. The
> interesting part isn't that number — it's that two of these invoices were trying to
> talk the agent into the wrong answer, and both of them still failed.

---

## 2 · Why you can't just point an agent at this — 0:20–0:50 (30s)

**On screen:** `FINDINGS.md` §1 and §2, the twelve-versus-eight split. Highlight the two
lists as you name them.

> Invoices come from outside your company. Anyone can write anything on one. So we
> measured it — twenty documented injection techniques against an ordinary extraction
> prompt. Twelve of them worked. Look at the split. Every payload that worked reads like
> normal business correspondence: "please note our updated banking details." Every
> payload that failed looks like an attack. A filter catches the ones that were already
> failing and misses the ones that work. You can't filter your way out of this.

---

## 3 · The design, running live — 0:50–1:30 (40s)

**On screen:** terminal. Run the local reader, then the resolver, in one paste.

```bash
PYTHONPATH=. python3 -c "
from praetor.agents import local_reader
from praetor.resolver import resolve
spans = {'p0:0.10_0.08_0.52_0.11': 'Acme Trading GmbH',
         'p0:0.62_0.08_0.92_0.11': 'INV-7781',
         'p0:0.62_0.82_0.92_0.86': '4,120.00'}
out = local_reader.read(spans).mapping;  print(out)
r = resolve(out, spans, 'deadbeef', 'DEMO');  print(r.rejected)"
```

> So the model never handles a value. The reader is quarantined — no tools, no memory —
> and it's a one-billion-parameter Gemma running on this laptop. It sees the document as
> numbered spans and may only answer with span IDs. Watch what it returned: three correct
> references, and then for currency it wrote "USD" — a literal value. The resolver
> rejects it, because "USD" is not a span reference. That isn't a guardrail I tuned. It's
> a type error. A compromised reader can point at the wrong span. It cannot introduce one.

**Note:** this is a real, unstaged failure. If Gemma returns four clean references on the
take, say so and move on — the point stands either way. Do not fake the rejection.

---

## 4 · One exception resolved, with evidence — 1:30–2:00 (30s)

**On screen:** the queue, scrolled to **V003_003**. Rest the cursor on the provenance
column, then the reasoning column.

> Detection is the easy half. A hundred and eighteen lines of rules already catch
> ninety-six percent of deviations and name the right reason every time they fire. What
> rules cannot do is read the note. V003_003 was flagged as a duplicate. The agent found
> the line saying it's a corrected reissue of a cancelled original, and cleared it.
> Eighteen of the sixty-five went that way, and this run none of them were wrong. Notice
> the value still carries its provenance — tainted, which span, which document hash.

---

## 5 · Two poisoned invoices, both overruled — 2:00–2:35 (35s)

**On screen:** click the **gate overrode 2** chip in the filter bar. The queue collapses
from 65 rows to exactly these two, both showing `GATE OVERRODE` with the refusal reason
underneath. Cut to `praetor/authority.py` for the last sentence.

Optional, 8s, if the pacing allows: select `V014_009` and press <kbd>u</kbd>. The audit
trail replays the document through all six stages — rules fired, agent voted resolve,
gate refused, awaiting a person. It is the architecture diagram with one document's data
in it, which is the single most on-theme shot in the video for an architecture prize.

> Now the two that matter. V019_007 carries a bank-account change and a note: "remittance
> update, we have changed banking providers." The agent believed it and voted to resolve.
> Refused — `bank_account` is privileged, and nothing written on the document releases it.
> V014_009 carries an injected approval ticket, AP-88213, supposedly from a Finance
> Director. The agent cited it and voted to resolve. Refused again — that ticket isn't in
> the buyer's register. An approval a document claims for itself is an assertion, not
> evidence. Fooled twice, correct twice.

---

## 6 · The human closes it — 2:35–3:05 (30s)

**On screen:** a terminal beside the queue. **There is no longer an "approve as" box** —
that was the point of the auth work, and the demo is stronger for it. Run these three
against the running server, then approve one row in the browser for real.

```bash
# 1. signed in as the approver, but the request body lies about who is approving
curl -s -b cj.txt -X POST localhost:8000/approve -H 'Content-Type: application/json' \
  -d '{"doc_id":"V000_004","tenant":"acme-industries","human_id":"agent:exception_resolver"}'
# -> "approved_by": "reviewer@acme-industries.test"   <- the body's claim is ignored

# 2. the same document a second time
# -> "V000_004 was already approved by reviewer@... at ..."   <- the schema's primary key

# 3. signed in as the auditor, who is a viewer
# -> "auditor@... does not hold 'approver' on acme-industries (role: viewer)"
```

> Something still has to pay these. So a person approves — one act that is both the
> segregation-of-duties control an auditor wants and the declassification the
> architecture needs. And the page cannot lie about who that person is. Watch: I'm
> posting an approval that claims to come from the agent, and the approval records *me*,
> because the identity comes from the session and the request body's opinion is thrown
> away. Post it twice and the database refuses — approving twice is a double payment, so
> idempotency is the primary key, not a check someone remembered to write. Every number
> here cost one rupee at list price, and nothing was charged.

**Verified 27 Aug** — all three responses above are copied from a live run, not written
from memory. Clear `out/praetor.db` approvals first (`make db` reports "approvals kept")
or row V000_004 already shows as approved when you roll.

---

## 7 · Limits, then close — 3:05–3:20 (15s)

**On screen:** `docs/architecture.png`, held still.

> It isn't a complete defence, and the gaps are written up rather than hidden. None of
> this is new science either — CaMeL and RTBAS, applied to accounts payable. The claim is
> narrow: here is how you build an agent the document can't hijack.

---

## Cloud Run — a decision to make before you roll

Cloud Run **has landed**: the queue is live at
`https://praetor-836128159455.asia-south1.run.app`, on Cloud Run `asia-south1` with state
in Cloud Firestore. Google Cloud infrastructure is a **mandatory gate** for every prize
category, so proving it on camera is worth more than any single measurement in this
script.

The Pub/Sub fan-out that an earlier draft of this section staged is **cut**, and must not
be filmed or claimed: 8 workers measured *slower* than 1, so there is nothing to
distribute ([FINDINGS §11](../FINDINGS.md)). Filming it would be staging a result we
disproved.

**Your call, one of two:**

- **Cheapest and safest — record beat 1 against the live URL instead of `localhost:8000`.**
  Costs zero extra seconds, and the `.run.app` domain in the address bar proves the
  mandatory gate in the first ten seconds. Risk: it is a live network dependency mid-take.
- **Safer for the take — stay on localhost and add 10s after beat 6:** cut to the live URL
  and the Cloud Run console showing the service in `asia-south1`, narrating one line. Costs
  10s, takes the total to 210s, still inside the 240s cap.

Either way the deployed container **calls no model**, so it cannot spend — say so, because
a judge will otherwise wonder what the live URL is costing you.
