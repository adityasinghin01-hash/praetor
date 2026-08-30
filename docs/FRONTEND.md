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

Gemini / Google Flow / Recraft. **Each block below is complete and paste-ready** — the
style header is already inside it, so paste one whole block, unedited. The header, for
reference when writing a sixth:

> Japanese manga pen-and-ink illustration. Pure black ink on white. No colour. No grey
> fill — every shade is made of screentone halftone dots or cross-hatching, the way a manga
> artist shades. Clean, confident linework with varying line weight: thicker on outer edges,
> thinner on interior detail. High contrast. Transparent background. No text, no readable
> letters, no numbers, no signature, no watermark.

Two rules that do the real work: **text is bars, never characters** — every model will try
to write words and every word will come out as garbage; and **shade only by dots or
hatching** — ask for grey and you get a muddy fill that kills the whole style.

### 1. The invoice sheet — worth more than the other four combined

```
Japanese manga pen-and-ink illustration. Pure black ink on white.
No colour. No grey fill — every shade is made of screentone halftone
dots or cross-hatching, the way a manga artist shades. Clean, confident
linework with varying line weight: thicker on outer edges, thinner on
interior detail. High contrast. Transparent background.
No text, no readable letters, no numbers, no signature, no watermark.

Subject: a single sheet of paper — an invoice — lying flat and seen
face-on, tilted about 8 degrees clockwise. The page is upright
portrait, A4 proportions.

On the page, lines of text are suggested as solid black horizontal
bars of varying length, never as readable characters. Two thin ruled
horizontal lines divide the page into three areas. In the lower third
there is a rectangular box outlined with a heavier stroke, containing
two short bars — this is the payment section and it should read as
the most deliberate element on the page.

The right edge of the sheet carries screentone shading, densest at
the very edge and thinning inward. Beneath the sheet, a cast shadow
drawn entirely in 45-degree cross-hatching, offset down and to the
right, with a slight curl at one corner where the paper lifts.

Composition: the sheet centred, filling most of the frame, nothing
else in the image. Flat lighting. No perspective distortion, no desk,
no hands, no background scenery.
```

### 2. A hand holding a page up to a camera

```
Japanese manga pen-and-ink illustration. Pure black ink on white.
No colour. No grey fill — every shade is made of screentone halftone
dots or cross-hatching, the way a manga artist shades. Clean, confident
linework with varying line weight: thicker on outer edges, thinner on
interior detail. High contrast. Transparent background.
No text, no readable letters, no numbers, no signature, no watermark.

Subject: one hand, seen from the back, holding a single sheet of paper
up and forward toward the viewer, as if presenting it to a camera. The
hand enters from the lower right and grips the sheet at its lower right
corner between thumb and fingers. Only the hand — no arm past the
wrist, no sleeve, no person.

The sheet is upright portrait, A4 proportions, tilted about 6 degrees,
and faces the viewer nearly flat with only slight foreshortening. Lines
of text on it are solid black horizontal bars of varying length, never
readable characters, and the paper bows very slightly under its own
weight, drawn as two long curved lines and a soft crease.

Knuckles, tendons and the fold of skin at the thumb joint are drawn in
fine contour lines. Shade the back of the hand and the underside of the
sheet with screentone dots; deepen to 45-degree cross-hatching where the
fingers pass behind the page.

Composition: hand and sheet together fill most of the frame, sheet
slightly above centre. Flat lighting. No background, no desk, no
camera, no phone in frame.
```

### 3. A hanko seal, mid-press

```
Japanese manga pen-and-ink illustration. Pure black ink on white.
No colour. No grey fill — every shade is made of screentone halftone
dots or cross-hatching, the way a manga artist shades. Clean, confident
linework with varying line weight: thicker on outer edges, thinner on
interior detail. High contrast. Transparent background.
No text, no readable letters, no numbers, no signature, no watermark.

Subject: a cylindrical Japanese hanko stamp, seen from a low
three-quarter angle, caught at the instant of pressing down onto a sheet
of paper. The barrel is upright and slightly tilted, its face pressed
flat against the page so the contact edge is hidden.

Around the base, the paper dimples: three or four short curved lines
radiating outward from under the stamp. Directly beside the stamp, a
circular impression already made on the page — a heavy ink ring with a
broken, uneven inner edge, its interior left empty of any character or
symbol.

The barrel carries a fine woodgrain of long parallel lines and screentone
dots along its right side, densest at the silhouette edge. A cast shadow
under the stamp in 45-degree cross-hatching, short and tight, so the
stamp reads as pressed hard rather than resting.

Composition: the stamp occupying the upper two-thirds of the frame, the
impression lower left, nothing else. Flat lighting. No hand, no ink pad,
no desk, no background.
```

### 4. The payment block, close up

```
Japanese manga pen-and-ink illustration. Pure black ink on white.
No colour. No grey fill — every shade is made of screentone halftone
dots or cross-hatching, the way a manga artist shades. Clean, confident
linework with varying line weight: thicker on outer edges, thinner on
interior detail. High contrast. Transparent background.
No text, no readable letters, no numbers, no signature, no watermark.

Subject: an extreme close-up crop of one part of a paper invoice — the
rectangular payment box — filling the frame, seen face-on and tilted
about 4 degrees clockwise. The crop is tight enough that the sheet's
outer edges are outside the frame on three sides.

The box is outlined in a heavy confident stroke, noticeably thicker than
anything else. Inside it, four solid black horizontal bars of differing
length stand for lines of detail, never readable characters, each paired
with a much shorter bar to its left standing for a label. A thin ruled
line separates the top two rows from the bottom two. One bar is drawn
thicker and longer than the rest — the amount — and sits alone on the
last row.

The paper around the box is left bare white. Screentone dots fall only
just inside the box's lower and right inner edges, suggesting depth
pressed into the page, and the box casts a fine 45-degree cross-hatched
shadow down and to the right.

Composition: the box centred and dominant, occupying about three
quarters of the frame width. Flat lighting. No perspective distortion,
no hands, no desk, no background.
```

### 5. A fanned stack of paper

```
Japanese manga pen-and-ink illustration. Pure black ink on white.
No colour. No grey fill — every shade is made of screentone halftone
dots or cross-hatching, the way a manga artist shades. Clean, confident
linework with varying line weight: thicker on outer edges, thinner on
interior detail. High contrast. Transparent background.
No text, no readable letters, no numbers, no signature, no watermark.

Subject: a loose stack of about twelve sheets of paper lying flat and
seen face-on from directly above, fanned so each sheet is offset a
little from the one beneath it, rotating gently clockwise down the
stack like a spread deck of cards. All sheets are upright portrait, A4
proportions.

Only the topmost sheet carries detail: solid black horizontal bars of
varying length standing for lines of text, never readable characters,
and one rectangular box outlined in a heavier stroke in its lower third.
Every sheet below shows nothing but its own outline — the eye should
read depth from the edges alone. Two or three sheets near the bottom sit
a little out of line, as if the stack has been handled.

Each sheet's right and lower edge carries a narrow band of screentone
dots, so the layers separate. Under the whole stack, a single cast
shadow in 45-degree cross-hatching, offset down and to the right,
denser directly beneath than at its outer edge. One corner of the top
sheet curls up slightly.

Composition: the stack centred, filling most of the frame, nothing else.
Flat lighting. No perspective distortion, no desk, no hands, no
background scenery.
```

2× transparent PNG, or SVG from Recraft. A scroll-scrubbed stamp sequence works on the
deployed site but not inside an artifact preview (16 MB cap on inlined data).

---

## The twelve, locked 30 Aug 2026

Chosen by Aditya from thirty live options, then two follow-ups after seeing them
assembled into screens 02 and 04. **These are settled — a screen that departs from one
is wrong, not creative.** Written as tokens and primitives at the foot of
`web/src/styles.css` so nothing has to restate the values.

| | Decision | Source |
|---|---|---|
| Buttons | **Ruled block** — key badge, inverts to solid ink | Watermelon `button` |
| Button animation | **Stamp press** — depresses onto its own shadow | CSS, `--press-travel` |
| Button background | **Paper grain**, and only on paper | `@react-bits/Noise` |
| Cursor | **Target lock** — four corners, converging to a point in open space | `@react-bits/TargetCursor` |
| Component arrival | **Lift and settle**, through a halftone that clears | `@react-bits/PixelCard` |
| Icons | **Draw on**, even hand, linear | SVG `stroke-dashoffset` |
| Slider | **Option wheel** | `@react-bits/OptionWheel` |
| Searching | **Scan bands**, behind the page, full frame | `@react-bits/Scanner` |
| Search bar | **Ruled line**, living on the key rail | Watermelon `input` |
| Toolbar | **Key rail** — `1` `2` `3` `Esc` as physical caps | CSS |

**Two answers that cost something, and why they went the way they did.**

*Line weight.* Flat black-on-white was rejected as "not that good" — correctly. The fix is
not colour, it is **three weights**: `--w-hair` 1px inside, `--w-mid` 1.5px on rules,
`--w-heavy` 2.5px on the outer edge and on the side the shadow falls. One uniform weight
reads as a wireframe. This is the same instruction the invoice-sheet prompt already gives
the image model, applied to the interface.

*Grain on an ink ground.* Tested, not assumed. At a density you can see, grain eats the
counters of small type on black; quiet enough to be safe, it does nothing at all. So grain
belongs to the paper and the ink state stays clean — `.grain` is cancelled by `.is-ink`.

*The cursor is one shape, not two.* The four corners never disappear; they converge into
the point and open back out. Anything that pops between two cursors is wrong.

**Deliberately dropped from the seventeen:** every component built on a gradient, glow,
glass or displacement — they cannot be restyled into this direction, only rewritten. The
list and the one-line reason for each is in [DECISIONS §33](DECISIONS.md).

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
