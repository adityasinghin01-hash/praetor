# Published results

The measurement artefacts behind every number in [FINDINGS.md](../FINDINGS.md), committed
so that a fresh clone reproduces the full demo — and the attack invariant test — without
an API key.

| File | Produced by | Reported in |
|---|---|---|
| `attacks_undefended.jsonl` | `make attacks` | FINDINGS §1–3 · the 60% undefended rate |
| `adjudication.jsonl` | `make adjudicate` | FINDINGS §6 · 28% fewer human touches, precision 1.000 |
| `readpath.jsonl` | `make readpath` | FINDINGS §10 · local Gemma, 20 of 25 documents had an answer refused |
| `readpath_gemini.jsonl` | `make readpath` + `--remote` | FINDINGS §10 · hosted Gemini, F1 1.000, no rejections |
| `twopath.jsonl` | `make twopath` | FINDINGS §18 · 8 of 100 beat one path, **0 of 100 beat both** |
| `model_armor.jsonl` | `make armor` | FINDINGS §19 · the filter flags 7 of the 8 that already failed |

Re-running either command writes to `out/`, which is gitignored and **takes precedence**
over this directory. So a fresh measurement always wins over the published one, and
these files are only the fallback.

Deterministic artefacts are not kept here: the corpus, the vendor master and the rules
exceptions all regenerate byte-identically from `make verify`. Nor is `pathb_stress.json`,
for the same reason — `make pathb` reproduces it exactly, with no model and no network.
The fitted weights are a derived artefact but they are *not* reproducible without being
re-fitted, so they live with the code at `praetor/pathb_weights.json` and carry a
fingerprint of the corpus they were fitted on; `tests/test_pathb.py` fails the build if
the two ever drift apart.

`twopath.jsonl` records both paths' answers as span ids, not just verdicts. That is what
lets `python eval/run_twopath.py --rescore` re-measure Path B against a changed fit
without calling the model again — the document is deterministic from the row.
