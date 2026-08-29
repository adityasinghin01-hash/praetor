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
| `ft_base_shuffled.jsonl` | `finetune/eval_reader.py` | FINDINGS §24 · base model on the held-out layout, F1 0.074 |
| `ft_tuned_shuffled.jsonl` | + `--adapter` | FINDINGS §24 · the fine-tune on the same layout, **F1 0.007** |
| `ft_base_trainlayout.jsonl` | + `--layout classic` | FINDINGS §24 · base on a trained layout, F1 0.051 |
| `ft_tuned_trainlayout.jsonl` | + both | FINDINGS §24 · the fine-tune on a trained layout, **F1 0.304** |
| `vsb_praetor_compromised.jsonl` | `benchmark/run_praetor.py --reader compromised` | FINDINGS §25 · **0 of 480** with the reader fully lost |
| `vsb_praetor_compromised_nob.jsonl` | + `--no-second-path` | FINDINGS §25 · the ablation: 20 of 480, utility 1.000 |
| `vsb_praetor_oracle.jsonl` | `--reader oracle` | FINDINGS §25 · a reader that cannot be wrong |
| `vsb_*.summary.json` | `benchmark/score.py --out` | FINDINGS §25 · the scored summaries |
| `adaptive_compromised.jsonl` | `make adaptive` | FINDINGS §26 · **0 of 450** reach the sink, budget 1 to 9 |
| `adaptive_adjudicated.jsonl` | `--local-adjudicator --docs 6` | FINDINGS §26 · 54 adjudications, **0 resolve** |
| `adaptive_hosted.jsonl` | `--docs 2` (hosted chain) | FINDINGS §26 · 18 adjudications, **0 resolve**, Rs 0.41 |
| `rule4_replay.json` | `eval/replay_rule4.py` | FINDINGS §27 · Rule 4 on = **0 of 65 resolved**, no model called |

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

The three `vsb_*` and the `adaptive_*` runs call **no model at all** — the reader is
replaced by a deterministic oracle or a fully compromised one — so they reproduce exactly
on any machine with no key, no Ollama and no GPU. The four `ft_*` runs need the arm64 MLX
environment described in [`finetune/README.md`](../finetune/README.md); the committed
adapter at `finetune/adapters/letterhead/` is what makes them repeatable without a
27-minute retrain.

`twopath.jsonl` records both paths' answers as span ids, not just verdicts. That is what
lets `python eval/run_twopath.py --rescore` re-measure Path B against a changed fit
without calling the model again — the document is deterministic from the row.
