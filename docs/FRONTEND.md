# The frontend — locked 29 Aug 2026

Phases 1–8 are done and the numbers are in `FINDINGS.md`. This file is the other half:
**what a person actually does with it.** Written after a judging pass found that a visitor
sees a spreadsheet, and that the strongest result in the repo appears on no screen at all.

Design and screens were agreed with Aditya. Nothing here is a suggestion.

---

## The one rule

> **Every screen ends in an action, never in information.**

The app currently *describes* Priya's job and makes her do all of it. Twelve things she
does by hand; the system already holds the answer to nine of them and asks her anyway.

Bad · `BANK_UNKNOWN — new account, never paid here before.`
Good · **"Do not pay this. Call Anja on +31 75 322 4478 — the number in your records, not
the invoice." [Confirmed] [Fraud]**

---

## Priya's twelve problems

| # | Problem | State |
|---|---|---|
| 7 | Who do I call, on what number | **done** |
| 12 | Prove I did my job | **done** |
| 1 | Is this a new account | show both accounts side by side |
| 2 | Did I already pay this | show the original beside it |
| 3 | Is this covered by a PO | we hold the register — answer it |
| 4 | Is this tax rate legitimate | show the usual rate and the note |
| 5 | Did they really move | old address vs new |
| 6 | What exactly is missing | name the field, draft the email |
| 8 | Which of the 47 matters | group into four jobs |
| 9 | Same supplier, five times | confirm once, clear all five |
| 10 | Typing a note every time | three canned notes on keys 1‑2‑3 |
| 11 | Making the phone call | **cannot be fully solved** — email the supplier instead |

Eleven of twelve are reachable. The twelfth becomes *"we emailed them, they replied"*.

---

## The screens

```
Sign in → TODAY ─┬─ Scan → Verdict ─┐
                 ├─ 4 jobs → card ──┤ 1/2/3 → next
                 └─ See what it did ─┘
   separate: What we stopped · Try to break it
```

**01 Today** — home. Scan and Upload as the two big entries, the overnight arrival count,
then four jobs with a time on each. One line about what the agent cleared.

**02 Scan** — camera opens immediately, no shutter button. Six live states:

| | |
|---|---|
| ⚪ | looking for a page… |
| 🔴 | **that is a screen, not paper** |
| 🔴 | that is not an invoice |
| 🟠 | too blurry — hold still |
| 🟠 | a corner is cut off |
| 🟢 | **got it — reading** → captures itself |

**03 Verdict** — one thing to do, three keys. Tapping any value opens the invoice with that
patch highlighted. `3` reopens the camera so a stack can be cleared without touching anything.

**04 A job** — one card at a time, full screen, no list. Four layouts: already paid ·
bank account changed · incomplete · not your decision. A key saves it and loads the next.

**05 See what it did** — the invoices cleared without her, and a spot-check.

**06 What we stopped** · **07 Try to break it** — already built, unchanged.

**Controls: `1` `2` `3` and `Esc`. Nothing else.**

---

## The visual direction

**Japanese manga pen-and-ink.** Not notebook, not handwriting, not dark SaaS.

| | |
|---|---|
| Display | **Shippori Mincho B1** — the mincho used in manga narration boxes |
| UI | **Zen Kaku Gothic New** |
| Grey | **screentone only** — halftone dots at three densities, plus 48–52° hatching and cross-hatching. Tone is masked with gradients so it thins across a panel |
| Colour | `#EFEEE8` paper · `#0B0B0B` ink · `#BE2B22` seal red. **One accent, used twice a page** |
| Gradients | **none**, anywhere. Grey is achieved by dot density, as ink does it |
| Structure | full-bleed sections, a continuous fixed ink field behind the whole page whose density is driven by scroll |

**The landing page's idea:** scrolling *is* the attack. The ink thickens as the fraud
closes in, goes black when the model believes it, and breaks open white at the `0`. The
reader knows why it is zero before they are told.

---

## Assets to generate

Gemini / Google Flow / Recraft. Prepend to every prompt:

> Japanese manga pen-and-ink illustration. Pure black ink on white, no colour, no grey
> fill — all shading done with screentone halftone dots and cross-hatching. Clean confident
> linework with varying line weight. High contrast. Transparent background. No text.

1. **The invoice sheet** — worth more than the other four combined
2. A hand holding a page up to a camera
3. A hanko seal, mid-press
4. The payment block, close up
5. A fanned stack of paper

2× transparent PNG, or SVG from Recraft. A scroll-scrubbed stamp sequence works on the
deployed site but not inside an artifact preview (16 MB cap on inlined data).

---

## Build order

Frontend goes in **beside each screen as it is finished**, never saved for the end.

1. **Scan** — the screen that proves the idea
2. **Today**
3. **Verdict and the four cards**
4. **See what it did**
5. **The landing page**, last, because it takes the longest

---

## Cancelled, and not to be reopened without Aditya

Giving the agent tool calls (it moves us onto CaMeL and Dromedary's ground, where their
defence needs an agent that clicks and a user giving instructions — neither of which a
batch pipeline has) · sourcing twenty real invoices · the card test against the dunning
block · the Vertex support case.
