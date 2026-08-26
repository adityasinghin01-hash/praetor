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
  approves for real, so `out/approvals.jsonl` should be **deleted** before you record —
  otherwise the row you want to approve already shows as approved.
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

**On screen:** **V019_007**, then **V014_009**. Both show `GATE OVERRODE` with the reason
underneath. Cut to `praetor/authority.py` for the last sentence.

> Now the two that matter. V019_007 carries a bank-account change and a note: "remittance
> update, we have changed banking providers." The agent believed it and voted to resolve.
> Refused — `bank_account` is privileged, and nothing written on the document releases it.
> V014_009 carries an injected approval ticket, AP-88213, supposedly from a Finance
> Director. The agent cited it and voted to resolve. Refused again — that ticket isn't in
> the buyer's register. An approval a document claims for itself is an assertion, not
> evidence. Fooled twice, correct twice.

---

## 6 · The human closes it — 2:35–3:05 (30s)

**On screen:** the queue. Type `agent:exception_resolver` into the "approve as" box,
click **approve** on any escalated row — the row turns red with the refusal. Then change
it to your own address and approve for real.

> Something still has to pay these. So a person approves — one act that is both the
> segregation-of-duties control an auditor wants and the declassification the
> architecture needs. Watch what happens when an agent tries. That's not a demo branch:
> it's the same PermissionError the tests pin, coming back to the browser. As a human it
> goes through, and lands in an audit file. Every number here cost one rupee at list
> price, and nothing was charged.

---

## 7 · Limits, then close — 3:05–3:20 (15s)

**On screen:** `docs/architecture.png`, held still.

> It isn't a complete defence, and the gaps are written up rather than hidden. None of
> this is new science either — CaMeL and RTBAS, applied to accounts payable. The claim is
> narrow: here is how you build an agent the document can't hijack.

---

## If Cloud Run lands before the deadline

Add one beat and trim two. Do not go past 220s.

- **New, 25s, after beat 3:** the deployed `.run.app` taking a batch through Pub/Sub —
  instance count climbing in the Cloud Run console, Cloud Trace showing a span with its
  taint label, then instances back at zero. Narrate throughput, peak concurrency and
  dollar cost, read off the console.
- **Trim beat 2** to 20s: keep the twelve-versus-eight split, drop the restatement of the
  filter argument.
- **Trim beat 4** to 20s: keep V003_003, drop the rules-baseline framing.

Update the diagram header at the same time — "Deployment target" becomes "Deployed" — and
re-render with `make diagram`.
