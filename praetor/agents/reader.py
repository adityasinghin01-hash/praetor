"""The quarantined reader.

The only component that sees untrusted document text. It therefore has:
  - no tools
  - no memory
  - no network beyond the model call
  - no ability to emit a value

It is shown the document's spans and must answer with span IDs only. Whatever it
returns goes through praetor.resolver, which rejects anything that is not a real
span reference. So a fully compromised reader can, at worst, point at the wrong
part of the document — it cannot introduce content that was never there.

Measured context (FINDINGS.md): 12 of 20 injection payloads persuaded an ordinary
extraction prompt to emit an attacker's bank account. This design makes that class
of compromise unable to change what gets paid.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from praetor import costguard

# Every model here must be Gemini 3.5+ to meet the hackathon requirement.
# gemini-3.5-flash returned 503 under load on 25 Aug, so the chain is not optional.
# flash-lite first: 5x cheaper than flash ($0.30/$2.50 vs $1.50/$9.00 per 1M tokens)
# and flash has been returning 503 under load. Both are Gemini 3.5+, so both meet
# the hackathon requirement.
MODEL_CHAIN = ("gemini-3.5-flash-lite", "gemini-3.5-flash")

WANTED_FIELDS = (
    "vendor_name", "invoice_number", "amount_total",
    "currency", "bank_account", "tax_rate", "vendor_address",
)

PROMPT = """You are reading a business document that has already been split into
numbered spans. Each span has an ID and its text.

Return ONLY a JSON object mapping each field to the ID of the span containing it.

Fields: {fields}

Rules:
- The value of every key MUST be a span ID exactly as written below.
- Never write the text itself. Only the span ID.
- If a field is not present, use null.
- Return nothing except the JSON object.

SPANS:
{spans}
"""


@dataclass
class ReaderResult:
    mapping: dict[str, str | None]
    model: str
    raw: str


def _api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    for env in (Path(__file__).resolve().parents[2] / ".env",
                Path.home() / "dev" / "hello_agent" / ".env"):
        if key:
            break
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GOOGLE_API_KEY=") and line.split("=", 1)[1].strip():
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("No GOOGLE_API_KEY (checked env, ./.env, ~/dev/hello_agent/.env)")
    return key


def _parse(raw: str) -> dict[str, str | None]:
    """Pull the JSON object out of the reply, tolerating code fences."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return {k: (None if v is None else str(v)) for k, v in obj.items()
            if k in WANTED_FIELDS}


def read(spans: dict[str, str], client=None, models=MODEL_CHAIN) -> ReaderResult:
    """Ask the model which span holds each field. Returns span IDs, never values."""
    if client is None:
        from google import genai
        client = genai.Client(api_key=_api_key())

    listing = "\n".join(f"{sid}\t{text}" for sid, text in spans.items())
    prompt = PROMPT.format(fields=", ".join(WANTED_FIELDS), spans=listing)

    last = ""
    for model in models:
        delay = 6.0
        for _ in range(3):
            try:
                costguard.check(model, len(prompt))
                r = client.models.generate_content(model=model, contents=prompt)
                u = getattr(r, "usage_metadata", None)
                costguard.record(model,
                                 getattr(u, "prompt_token_count", 0) or int(len(prompt) / 3.5),
                                 getattr(u, "candidates_token_count", 0) or 80)
                raw = r.text or ""
                return ReaderResult(mapping=_parse(raw), model=model, raw=raw)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                last = msg
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    time.sleep(delay)
                    delay = min(delay * 1.6, 45)
                    continue
                if "503" in msg or "UNAVAILABLE" in msg:
                    break        # overloaded — switch model rather than wait
                raise
    raise RuntimeError(f"all models failed: {last[:160]}")
