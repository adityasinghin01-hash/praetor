# Published results

The measurement artefacts behind every number in [FINDINGS.md](../FINDINGS.md), committed
so that a fresh clone reproduces the full demo — and the attack invariant test — without
an API key.

| File | Produced by | Reported in |
|---|---|---|
| `attacks_undefended.jsonl` | `make attacks` | FINDINGS §1–3 · the 60% undefended rate |
| `adjudication.jsonl` | `make adjudicate` | FINDINGS §6 · 28% fewer human touches, precision 1.000 |

Re-running either command writes to `out/`, which is gitignored and **takes precedence**
over this directory. So a fresh measurement always wins over the published one, and
these files are only the fallback.

Deterministic artefacts are not kept here: the corpus, the vendor master and the rules
exceptions all regenerate byte-identically from `make verify`.
