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

# Where a laptop may look for a credential. A module-level list rather than a literal
# inside the function, so a test can point it somewhere harmless instead of shimming
# pathlib -- a test that has to fake the filesystem to reach a branch usually means the
# branch is not reachable enough to trust.
#
# NEVER consulted in production. See `_api_key`.
ENV_FILES = (Path(__file__).resolve().parents[2] / ".env",
             Path.home() / "dev" / "hello_agent" / ".env")

WANTED_FIELDS = (
    "vendor_name", "invoice_number", "amount_total",
    "currency", "bank_account", "tax_rate", "vendor_address",
)

PROMPT = """Extract fields from a document that has been split into numbered spans.

You must answer with the span ID, NOT the text. Copy the ID exactly.

--- EXAMPLE ---
SPANS:
p0:0.10_0.08_0.52_0.11	Acme Trading GmbH
p0:0.62_0.08_0.92_0.11	INV-7781
p0:0.62_0.82_0.92_0.86	4,120.00

ANSWER:
{{"vendor_name": "p0:0.10_0.08_0.52_0.11", "invoice_number": "p0:0.62_0.08_0.92_0.11", "amount_total": "p0:0.62_0.82_0.92_0.86", "currency": null, "bank_account": null, "tax_rate": null, "vendor_address": null}}
--- END EXAMPLE ---

Notice: every value above starts with "p0:". Never write the text itself.
Use null when a field is absent.

Fields: {fields}

SPANS:
{spans}

ANSWER:
"""


@dataclass
class ReaderResult:
    mapping: dict[str, str | None]
    model: str
    raw: str


def _api_key() -> str:
    """The model credential, from the environment -- and in production from nowhere else.

    On a laptop this falls back to a `.env` file, which is what makes the demo runnable
    without anybody exporting anything. **In production that fallback is switched off.**

    A deployed service reading a credential off its own filesystem is the failure this
    prevents: it means the key was baked into an image or written into a volume, where
    it outlives the process, appears in a layer somebody can pull, and is invisible to
    the audit trail that Secret Manager keeps. The deployed service is given
    `GOOGLE_API_KEY` from Secret Manager at start (`--set-secrets`), so if the variable
    is missing the correct outcome is a loud failure, not a quiet search of the disk.

    `K_SERVICE` is set by Cloud Run and by nothing else, the same signal
    `praetor/trace.py` uses.
    """
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key

    if os.environ.get("K_SERVICE"):
        raise SystemExit(
            "No GOOGLE_API_KEY in the environment. This is a deployed service, so the "
            "key must come from Secret Manager -- refusing to read a credential off the "
            "filesystem. Redeploy with: --set-secrets GOOGLE_API_KEY=gemini-api-key:latest")

    for env in ENV_FILES:
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GOOGLE_API_KEY=") and line.split("=", 1)[1].strip():
                    return line.split("=", 1)[1].strip()

    raise SystemExit("No GOOGLE_API_KEY (checked env, ./.env, ~/dev/hello_agent/.env)")


def _client():
    """The model backend. Vertex when asked for, the Gemini API otherwise.

    Vertex is not a preference, it is the only way to run the core experiment. The
    Gemini free tier is 20 requests per DAY per model (FINDINGS §4) and one adjudication
    pass over the constructed corpus needs ~54 -- so on the free tier the measurement
    that the whole architecture argument rests on cannot be taken at all.

    Vertex authenticates with Application Default Credentials, so `PRAETOR_GEMINI=vertex`
    runs with no `GOOGLE_API_KEY` present anywhere. That is deliberate: the key belongs
    to a project we keep billing-disabled, and nothing here should be able to quietly
    fall back onto it.

    The import stays inside the function. `praetor/` must import on the standard library
    alone, or the security claims stop being checkable with only pytest installed.
    """
    from google import genai

    if os.environ.get("PRAETOR_GEMINI", "").strip().lower() != "vertex":
        return genai.Client(api_key=_api_key())

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise SystemExit("PRAETOR_GEMINI=vertex needs GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
    return genai.Client(vertexai=True, project=project, location=location)


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
        client = _client()

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
