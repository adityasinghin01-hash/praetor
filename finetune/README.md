# Fine-tuning the quarantined reader, on this machine

The on-device reader scores **F1 0.040** (`FINDINGS.md` §10). It gets most fields wrong
and has never once populated `bank_account`. This directory trains it to do the job, on
an Apple GPU, with no cloud and no API key.

Everything here runs on **your own hardware**. Nothing is uploaded.

---

## The gotcha, first

**The project's `.venv` cannot run this.** It is an x86_64 Python 3.13 under Rosetta:

```
$ .venv/bin/python -c "import sysconfig; print(sysconfig.get_platform())"
macosx-26.0-x86_64
```

MLX ships arm64 wheels only, so `pip install mlx` there fails with
`No matching distribution found`. The arm64 Homebrew Python is the one to use:

```
$ /opt/homebrew/bin/python3 -c "import sysconfig; print(sysconfig.get_platform())"
macosx-26.0-arm64
```

So this directory gets a **second virtual environment**, `.venv-mlx`, and the project's
`.venv` is left alone.

That `praetor/` imports cleanly under a different Python, on a different architecture,
with nothing installed, is not luck — it is the standard-library-only rule paying for
itself. The fine-tuning harness imports the real prompt and the real resolver, so the
model is trained against the contract the product actually sends.

---

## One-time setup (~2 minutes, no GPU)

```bash
cd ~/dev/praetor
/opt/homebrew/bin/python3 -m venv .venv-mlx
.venv-mlx/bin/pip install --upgrade pip
.venv-mlx/bin/pip install mlx-lm
```

Check it landed:

```bash
.venv-mlx/bin/python -c "import mlx.core as mx; print(mx.default_device())"
# Device(gpu, 0)
```

`.venv-mlx/` is gitignored.

---

## Step 1 — build the training data

```bash
.venv/bin/python finetune/prepare.py --holdout letterhead
```

```
holdout layout : letterhead   span order: shuffled
train 250   valid 30   test 70   -> finetune/data
train layouts  : banded, classic, compact, remit_right
prompt sha256  : f220d6d6267cce27  (praetor.agents.reader.PROMPT)
```

Two things this does that matter more than the fine-tune itself:

**Held out by layout, not by document.** The test set is every document of one page
template the model never sees in training. Held out by document, a model memorises five
templates and looks strong — that is what `FINDINGS.md` §17 caught happening to Path B.

**The span listing is shuffled.** Measured before any training: `payment_iban` is the
**fifth span in 342 of 342** annotations. Train on the natural order and the model can
score perfectly by answering "the fifth line" while reading nothing — the same shortcut
that inflated the old F1 to 0.384. `--order natural` exists so the gap can be measured
rather than assumed.

The prompt is imported from `praetor.agents.reader.PROMPT`, never copied, so the training
data cannot drift from what the shipped reader sends.

---

## Step 2 — train

**Quit Ollama first.** It holds a model in GPU memory and this run has already died once
with `[METAL] Command buffer execution failed: Insufficient Memory`:

```bash
pkill -f "ollama serve"
```

Then:

```bash
cd ~/dev/praetor
PYTHONPATH=. .venv-mlx/bin/python -m mlx_lm lora \
  --model mlx-community/gemma-3-1b-it-4bit \
  --train --data finetune/data \
  --fine-tune-type lora --mask-prompt \
  --num-layers 8 --batch-size 1 --iters 300 \
  --max-seq-length 1024 --learning-rate 1e-4 \
  --steps-per-report 25 --steps-per-eval 150 --val-batches 8 \
  --grad-checkpoint --clear-cache-threshold 1 \
  --adapter-path finetune/adapters/letterhead --save-every 100 --seed 0
```

### What each flag is for

| Flag | Why |
|---|---|
| `mlx-community/gemma-3-1b-it-4bit` | 4-bit base, ~800 MB. QLoRA. The Ollama baseline is also 4-bit, so the comparison is like for like. |
| `--fine-tune-type lora` | Trains 2.0 M of 1.3 B parameters (0.154%). A full fine-tune does not fit in 8 GB. |
| `--mask-prompt` | Loss on the **answer only**. Without it the model spends its capacity learning to reproduce the prompt. |
| `--num-layers 8` | LoRA on the last 8 blocks. More layers is more memory for very little here. |
| `--batch-size 1` | 8 GB is shared between CPU and GPU. Sequences run to 1007 tokens. Batch 2 is where it starts failing. |
| `--max-seq-length 1024` | Measured: longest training example is **1007 tokens**. |
| `--grad-checkpoint` | Recomputes activations instead of storing them. **This is what stops the out-of-memory crash.** Costs ~2x speed: 2.8 s/iter → 5.4 s/iter. |
| `--clear-cache-threshold 1` | Returns GPU memory aggressively rather than holding a cache. |
| `--seed 0` | Same run, same weights. |
| `--save-every 100` | A checkpoint every 100 iterations, so a crash or a `Ctrl-C` costs at most 100 iterations. |

### What you should see

```
Trainable parameters: 0.154% (2.007M/1301.876M)
Starting training..., iters: 300
Iter 1: Val loss 0.551, Val took 20.951s
Iter 25: Train loss 0.162, ...
Iter 50: Train loss 0.094, ...
Iter 100: Train loss 0.073, ...
```

Val loss 0.551 is the untrained model. Train loss under 0.10 by iteration 50 is the task
being easy — it is rigid JSON with span ids, not a style to absorb.

**Timing, measured on an M1 with 8 GB:** 5.4 s/iteration. 300 iterations ≈ **27 minutes**,
600 ≈ 54 minutes. The GPU is pinned throughout and the machine gets hot; that is the
job, not a fault.

**If it dies with `Insufficient Memory`:** quit Ollama and any browser with many tabs,
then re-run. It resumes from the last checkpoint with
`--resume-adapter-file finetune/adapters/letterhead/adapters.safetensors`.

Output: `finetune/adapters/letterhead/adapters.safetensors`, about 8 MB.

---

## Step 3 — score it, against the number it has to beat

The same scorer `eval/run_readpath.py` uses (`eval/readscore.py`), so the fine-tune, the
base model, the Ollama reader and the hosted reader all land in one table.

```bash
# the base model, on the held-out layout — this is the "before"
PYTHONPATH=. .venv-mlx/bin/python finetune/eval_reader.py \
  --order shuffled --out out/ft_base_shuffled.jsonl

# the fine-tune — the "after"
PYTHONPATH=. .venv-mlx/bin/python finetune/eval_reader.py \
  --adapter finetune/adapters/letterhead \
  --order shuffled --out out/ft_tuned_shuffled.jsonl
```

70 documents at 5.2 s each ≈ **6 minutes** per run.

Run both again with `--order natural` to measure the list-position shortcut. If the
fine-tune scores well on `natural` and badly on `shuffled`, it learned "the fifth line".

### What to look at, in order

1. **`bank_account` correct** — the privileged field. It was 0 of 25 before.
2. **Rejections by the resolver** — every literal the model tried to hand back instead of
   a reference. This number is a property of `praetor/guard.py`, not of the model, and it
   should not improve just because the model did.
3. **F1** — last, because it is the number that changes with every model release.

The claim being tested is not "the fine-tune scores better". It is that **accuracy is a
property of the model and refusal is a property of the architecture**. If F1 rises by an
order of magnitude and the rejection behaviour is unchanged, that is the result.

---

## Why not Colab or Kaggle

Both work and both are free — Kaggle gives 30 GPU-hours a week on a T4, which is more
than this needs. Two reasons it is not the default here:

- They run **torch + peft**, so the adapters come back in HuggingFace format and have to
  be converted before anything local can load them.
- The whole point of the on-device reader is that it is on-device: no key, no quota, no
  cost, and reproducible by anyone with the repo. A training step that needs somebody's
  cloud account weakens that.

Google Cloud is the wrong tool here regardless: **Vertex AI Training sits inside the
dunning block** on the billing account, and a Compute Engine GPU VM needs a quota
increase that does not arrive the same day.

---

## Doing it properly: five folds

One held-out layout is one measurement. The rigorous version rotates:

```bash
for L in banded classic compact letterhead remit_right; do
  .venv/bin/python finetune/prepare.py --holdout $L
  PYTHONPATH=. .venv-mlx/bin/python -m mlx_lm lora \
    --model mlx-community/gemma-3-1b-it-4bit --train --data finetune/data \
    --fine-tune-type lora --mask-prompt --num-layers 8 --batch-size 1 \
    --iters 300 --max-seq-length 1024 --learning-rate 1e-4 --grad-checkpoint \
    --clear-cache-threshold 1 --adapter-path finetune/adapters/$L --seed 0
done
```

Five folds at 300 iterations is **~2 hours 15 minutes** of pinned GPU, plus scoring.
`prepare.py` overwrites `finetune/data/` each time, so run the scoring for a fold before
moving to the next, or the test split will not match the adapter.
