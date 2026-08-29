"""Model backends for the VSB reference runs. One place, three backends.

    ollama   the on-device Gemma the shipped reader already uses (praetor/agents)
    mlx      a local MLX model, with or without LoRA adapters -- the fine-tune
    gemini   the hosted reader (praetor/agents/reader.py), capped by costguard

`mlx` needs the arm64 environment described in finetune/README.md. The other two run
anywhere. Nothing here is imported by `praetor/`: the kernel stays standard library
only, and a benchmark harness is not allowed to be the thing that breaks that.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praetor.agents import local_reader  # noqa: E402
from praetor.agents import reader as remote_reader  # noqa: E402


def ollama(model: str = local_reader.DEFAULT_MODEL):
    if not local_reader.available(model):
        raise SystemExit(f"{model} is not available. `ollama serve` and `ollama pull {model}`")

    def run(prompt: str) -> str:
        return local_reader.generate(prompt, model=model)
    return run, f"ollama/{model}"


def mlx(model: str, adapter: str | None = None, max_tokens: int = 260):
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    m, tok = load(model, adapter_path=adapter)
    sampler = make_sampler(temp=0.0)

    def run(prompt: str) -> str:
        text = tok.apply_chat_template([{"role": "user", "content": prompt}],
                                       add_generation_prompt=True, tokenize=False)
        return generate(m, tok, prompt=text, max_tokens=max_tokens,
                        sampler=sampler, verbose=False)
    return run, f"mlx/{Path(model).name}" + (f"+{Path(adapter).name}" if adapter else "")


def gemini(models=remote_reader.MODEL_CHAIN, max_tokens: int = 260):
    """The hosted chain, through the same client and the same spending ceiling the
    product uses. The free tier is 20 requests per day per model (FINDINGS §4), so a
    full VSB run is not affordable on it -- use --tier core --limit."""
    import time

    from praetor import costguard
    client = remote_reader._client()

    def run(prompt: str) -> str:
        last = ""
        for model in models:
            delay = 6.0
            for _ in range(3):
                try:
                    costguard.check(model, len(prompt))
                    r = client.models.generate_content(model=model, contents=prompt)
                    u = getattr(r, "usage_metadata", None)
                    costguard.record(
                        model,
                        getattr(u, "prompt_token_count", 0) or int(len(prompt) / 3.5),
                        getattr(u, "candidates_token_count", 0) or 80)
                    return r.text or ""
                except costguard.BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001
                    last = str(e)
                    if "429" in last or "RESOURCE_EXHAUSTED" in last:
                        time.sleep(delay)
                        delay = min(delay * 1.6, 45)
                        continue
                    if "503" in last or "UNAVAILABLE" in last:
                        break
                    raise
        raise RuntimeError(f"all models failed: {last[:160]}")
    return run, "/".join(models)


def build(kind: str, model: str = "", adapter: str = "", max_tokens: int = 260):
    if kind == "ollama":
        return ollama(model or local_reader.DEFAULT_MODEL)
    if kind == "mlx":
        return mlx(model or "mlx-community/gemma-3-1b-it-4bit", adapter or None, max_tokens)
    if kind == "gemini":
        return gemini()
    raise SystemExit(f"unknown reader {kind!r}")
