#!/bin/bash
# The five-fold layout rotation. One held-out layout is one measurement; FINDINGS §24's
# first number held out `letterhead`, whose left margin is 0.28 against 0.05-0.08 for
# every other layout -- the worst case, and n=1 cannot tell a worst case from a typical
# one. This runs the rest.
#
# prepare.py overwrites finetune/data/ each time, so each fold is scored before the next
# one starts. Roughly 31 minutes per fold on an M1: 27 training, 4 scoring.
set -euo pipefail
cd "$(dirname "$0")/.."
LAYOUTS="${1:-banded classic compact remit_right}"
N="${N:-25}"

for L in $LAYOUTS; do
  echo "=================== fold: holding out $L"
  .venv/bin/python finetune/prepare.py --holdout "$L"

  PYTHONPATH=. .venv-mlx/bin/python -m mlx_lm lora \
    --model mlx-community/gemma-3-1b-it-4bit \
    --train --data finetune/data \
    --fine-tune-type lora --mask-prompt \
    --num-layers 8 --batch-size 1 --iters 300 \
    --max-seq-length 1024 --learning-rate 1e-4 \
    --steps-per-report 100 --steps-per-eval 300 --val-batches 8 \
    --grad-checkpoint --clear-cache-threshold 1 \
    --adapter-path "finetune/adapters/$L" --save-every 150 --seed 0

  PYTHONPATH=. .venv-mlx/bin/python finetune/eval_reader.py \
    --limit "$N" --order shuffled --out "out/fold_${L}_base.jsonl"
  PYTHONPATH=. .venv-mlx/bin/python finetune/eval_reader.py \
    --adapter "finetune/adapters/$L" --limit "$N" --order shuffled \
    --out "out/fold_${L}_tuned.jsonl"
  echo "=================== fold $L done"
done
