"""The quarantined reader, running locally on Gemma via Ollama.

Same contract as agents/reader.read(): it is shown the document's spans and must
answer with span IDs only. praetor.resolver rejects anything that is not a real
span reference, so a compromised local model is no more dangerous than a
compromised remote one.

Why local: this is the component that reads untrusted document text, and it is
exactly the component that should NOT be a large privileged model with network
access. A small model, on this machine, with no tools, is the honest form of
"quarantined". That it also costs nothing and has no quota is a bonus, not the
reason.

No API key, no billing, no rate limit. Requires `ollama serve` running.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from praetor.agents.reader import PROMPT, WANTED_FIELDS, _parse

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma3:1b"


@dataclass
class LocalReaderResult:
    mapping: dict[str, str | None]
    model: str
    raw: str


class OllamaUnavailable(RuntimeError):
    """Ollama is not running, or the model is not pulled."""


def available(model: str = DEFAULT_MODEL) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=4) as r:
            tags = json.load(r)
    except Exception:  # noqa: BLE001
        return False
    # Exact tag, not a family prefix: having gemma3:1b pulled does not mean
    # gemma3:4b will answer. A prefix match here reports available() == True and
    # then 404s inside generate(), which is a worse failure than saying no.
    return any(model in (m.get("name"), m.get("model"))
               for m in tags.get("models", []))


def generate(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 180) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        # deterministic: we want the same span chosen for the same document
        "options": {"temperature": 0.0, "num_predict": 220},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("response", "")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise OllamaUnavailable(
                f"Ollama is running but {model!r} is not pulled. Pull it with:\n"
                f"  ollama pull {model}") from e
        raise OllamaUnavailable(f"Ollama returned HTTP {e.code} for {model!r}") from e
    except urllib.error.URLError as e:
        raise OllamaUnavailable(
            f"cannot reach Ollama at {OLLAMA_URL} ({e}). Start it with:\n"
            f"  ollama serve") from e


def read(spans: dict[str, str], model: str = DEFAULT_MODEL) -> LocalReaderResult:
    """Ask the local model which span holds each field. Returns span IDs, never values."""
    listing = "\n".join(f"{sid}\t{text}" for sid, text in spans.items())
    prompt = PROMPT.format(fields=", ".join(WANTED_FIELDS), spans=listing)
    raw = generate(prompt, model=model)
    return LocalReaderResult(mapping=_parse(raw), model=f"ollama/{model}", raw=raw)
