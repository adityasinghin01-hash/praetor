# Vertex AI support case — draft

Everything below was verified on 28 Aug 2026. Re-run the commands before filing, so the
case says what is true on the day it is read.

**Category:** Billing (free on every support tier — a paid support plan is not needed)
**Console path:** Support → Cases → Create case
**Project:** `praetor-run-2026` · number `836128159455`
**Billing account:** `0191FD-213A79-6F6D68`

---

## Subject

Vertex AI returns 403 "Lightning dunning decision is deny" on a project with billing
enabled and an open billing account

## Body — paste this

> Vertex AI is refusing every request on project `praetor-run-2026` (project number
> `836128159455`) with:
>
> ```
> 403 PERMISSION_DENIED
> Lightning dunning decision is deny for project: projects/836128159455
> ```
>
> This is not a quota error, an IAM error or a regional issue. I have confirmed the
> following:
>
> - The error is identical in `asia-south1`, `us-central1` and `europe-west4`, so it is
>   project-wide rather than regional.
> - Billing is enabled on the project and linked to billing account
>   `0191FD-213A79-6F6D68`, which is open.
> - Other paid services on the same project and the same billing account work normally.
>   Document AI (Invoice Parser, `asia-south1`) has processed pages today and been
>   charged for them.
> - `aiplatform.googleapis.com` is enabled on the project.
> - The calling principal has the necessary IAM roles; the error text is about a dunning
>   decision, not about permissions.
>
> The message appears to be a payment-risk or credit hold applied on Google's side. There
> is no setting in the project or the billing account that I can change to clear it.
>
> Please tell me why the dunning decision is `deny` for this project and what is needed
> to clear it.

---

## Reproduce, for the case or for yourself

```bash
TOKEN=$(gcloud auth print-access-token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "https://asia-south1-aiplatform.googleapis.com/v1/projects/praetor-run-2026/locations/asia-south1/publishers/google/models/gemini-3.5-flash-lite:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"ok"}]}]}'
```

Evidence that billing is not the cause:

```bash
gcloud billing projects describe praetor-run-2026     # billingEnabled: true
gcloud billing accounts describe 0191FD-213A79-6F6D68 # open: True
```

---

## What this actually blocks, and what it does not

**It does not block the project.** Everything measured in `FINDINGS.md` was produced
without Vertex. The Gemini API key path and Ollama both work, and
`praetor/agents/reader.py` already carries the `PRAETOR_GEMINI=vertex` switch for the day
it clears.

**What it blocked was volume.** `FINDINGS.md` §13 records Rule 4 as built, tested and
**off by default**, because turning it on changes outcomes and re-measuring §6 needs about
65 model calls. §4 says the Gemini free tier is 20 requests per day per model, which made
that measurement unreachable and made Vertex the way to get it.

**That premise now looks stale.** On 28 Aug, `eval/run_twopath.py` made **100 consecutive
calls** to `gemini-3.5-flash-lite` in a single run, twice, with no `429` and no
`RESOURCE_EXHAUSTED` — 200 calls in a day against a documented ceiling of 20. So the
65-call re-measurement is probably reachable on the Gemini path today, without Vertex and
without a support case.

**Do that first.** If `eval/run_adjudication.py` completes with Rule 4 enabled, Vertex
stops being on the critical path for anything currently planned, and the case becomes
housekeeping rather than a blocker.
