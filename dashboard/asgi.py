"""The same contract, on FastAPI — plus paging, live updates and uploads.

`docs/PLAN.md` Phase 6 puts the transport first, and gives the reason: the frontend gets
built twice otherwise. A React client written against a stdlib `http.server` that cannot
page, cannot stream and cannot accept a file is a client that gets rewritten the moment
any of those arrive.

**The JSON contract does not change.** Every response here is produced by the same pure
functions in `dashboard/api.py` that `dashboard/serve.py` calls. That is not a claim in a
docstring: `tests/test_asgi.py::test_both_transports_return_the_same_json` issues the same
request through both and compares, so a divergence fails the build rather than surfacing
as a frontend bug.

## Why serve.py stays

`dashboard/serve.py` is standard library only, and `make demo` runs on a laptop with
nothing installed. That property is worth keeping: a judge cloning this repository can
reach the queue without a package index. So this is an *addition*, not a replacement —
FastAPI where it is installed, `http.server` where it is not, one contract behind both.

## What is genuinely new here

**Paging.** `/v1/queue` takes `page` and `per_page`. Paging is a window, never a filter:
the response always carries the full `waiting` count and the page metadata needed to
reach every row, and `tests/test_asgi.py` asserts that walking the pages returns every
row exactly once. `praetor/queueing.py` refuses to shorten a queue for the same reason —
a row nobody can reach is a row nobody will look at.

**Live updates.** `/v1/events` is Server-Sent Events, not WebSockets: the traffic is one
directional, SSE reconnects by itself, and it survives the proxies in front of Cloud Run
without an upgrade handshake. It streams a small event when the queue changes so the
client re-fetches; **it never streams queue content**, so a stale or partially delivered
stream cannot put wrong data on a screen.

**Uploads.** `POST /v1/documents` accepts a PDF and runs `ingest/pipeline.py` — the same
path Eventarc drives in the cloud, so there is one pipeline and not a second one for
things a person uploads.

Security headers, rate limiting and the session rules are the ones `serve.py` already
enforces, imported from it rather than restated, because two copies of a security header
list is one copy that will fall behind.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from dashboard import api, ratelimit, serve
from praetor import store

ROOT = Path(__file__).resolve().parents[1]

# One page of a queue. Small enough that a phone renders it quickly, large enough that a
# day's exceptions are a few pages rather than forty.
DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 200

# A PDF nobody would send by accident. Rejected before it is read, not after: the point of
# a size limit is to avoid holding the bytes at all.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(
    title="PRAETOR",
    description="The review queue. Same JSON as dashboard/serve.py, different transport.",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)


# --------------------------------------------------------------------------- plumbing

@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    """The headers and the rate limit `serve.py` already applies.

    Imported from `serve` rather than restated. Two copies of a security header list is
    one copy that falls behind, and the one that falls behind is the one nobody reads.
    """
    limiter = serve.RUN_LIMIT if request.method == "POST" else serve.READ_LIMIT
    key = ratelimit.caller_key(request.headers, (request.client.host if request.client
                                                 else "", 0))
    allowed, retry = limiter.check(key)
    if not allowed:
        response = JSONResponse(
            {"error": "Too many requests. Please wait a moment and try again."},
            status_code=429, headers={"Retry-After": str(retry)})
    else:
        response = await call_next(request)

    for header, value in serve.SECURITY_HEADERS.items():
        response.headers[header] = value
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Cache-Control"] = "no-store"
    # BaseHTTPRequestHandler advertises the Python version; uvicorn advertises itself.
    # Neither is anybody's business.
    response.headers["Server"] = "praetor"
    return response


def _conn():
    return serve.db().connect()


def _rows(tenant: str) -> list[dict]:
    """Rows from the database when there is one, from files otherwise -- `serve.py`'s
    rule, so `make demo` behaves identically on either transport."""
    from dashboard import build

    if store.DB_PATH.exists() or serve.firestore_backend():
        rows, _ = build.rows_from_db(tenant)
    else:
        rows, _ = build.rows_from_files()
    return rows


async def session(request: Request,
                  tenant: str = Query(default=store.DEFAULT_TENANT)) -> tuple[str, str]:
    """The signed-in user and the client company they are allowed to see.

    The identity comes from the session cookie and never from the request body or a
    query parameter -- DECISIONS #11. A caller may *ask* for a tenant; whether they get
    it is decided here.
    """
    from praetor import auth

    token = request.cookies.get(serve.COOKIE)
    conn = _conn()
    user = auth.session_user(conn, token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="not signed in")
    if serve.db().role_of(conn, user, tenant) is None:
        raise HTTPException(status_code=403, detail="not a member of this client")
    return user, tenant


# ------------------------------------------------------------------------- the queue

def paginate(payload: dict, page: int, per_page: int) -> dict:
    """Window the rows, and say enough that every row is still reachable.

    Paging is a window and never a filter. The unpaged totals stay exactly as
    `dashboard/api.py` computed them, and `page`/`pages`/`per_page` are added alongside,
    so a client can always walk to the end. A response that quietly returned 25 of 65
    rows with no way to know would be the queue-shortening `praetor/queueing.py` refuses
    to do, arriving by a different route.
    """
    rows = payload.get("rows", [])
    total = len(rows)
    pages = max(1, -(-total // per_page))
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return {**payload,
            "rows": rows[start:start + per_page],
            "page": {"page": page, "per_page": per_page, "pages": pages,
                     "total_rows": total,
                     "has_next": page < pages, "has_previous": page > 1}}


@app.get("/v1/queue")
async def queue(page: int = Query(1, ge=1),
                per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
                who=Depends(session)) -> dict:
    _, tenant = who
    return paginate(api.queue(_rows(tenant)), page, per_page)


@app.get("/v1/stopped")
async def stopped(who=Depends(session)) -> dict:
    _, tenant = who
    return api.stopped(_rows(tenant))


@app.get("/v1/notes")
async def notes(doc_id: str = Query(""), who=Depends(session)) -> dict:
    _, tenant = who
    return {"notes": store.notes_for(_conn(), tenant, doc_id)}


@app.post("/v1/notes")
async def add_note(request: Request, who=Depends(session)) -> dict:
    user, tenant = who
    body = await request.json()
    try:
        # The author is the session, never the body. Same rule as approval: a
        # self-declared identity is not an identity. DECISIONS #11.
        return store.add_note(_conn(), tenant, str(body.get("doc_id", "")), user,
                              str(body.get("body", "")), str(body.get("kind", "note")))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ------------------------------------------------------------- try to break it (open)

@app.get("/v1/gauntlet/documents")
async def gauntlet_documents() -> dict:
    return api.gauntlet_documents()


@app.get("/v1/gauntlet/examples")
async def gauntlet_examples() -> dict:
    return api.gauntlet_examples()


@app.get("/v1/gauntlet/document")
async def gauntlet_document(id: str = Query("")) -> dict:  # noqa: A002
    try:
        return api.gauntlet_document(id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="no such invoice") from e


@app.post("/v1/gauntlet/run")
async def gauntlet_run(request: Request) -> dict:
    body = await request.json()
    try:
        return api.gauntlet_run(str(body.get("doc_id", "")), str(body.get("text", "")))
    except KeyError as e:
        raise HTTPException(status_code=404, detail="no such invoice") from e


# ------------------------------------------------------------------- live updates

def queue_version(tenant: str) -> str:
    """A cheap fingerprint of the queue, used only to decide whether to tell the client
    something changed. Deliberately not the queue itself."""
    rows = _rows(tenant)
    return f"{len(rows)}:{hash(tuple(sorted(str(r.get('doc_id')) for r in rows))) & 0xffffff:06x}"


@app.get("/v1/events")
async def events(request: Request, who=Depends(session)) -> StreamingResponse:
    """Server-Sent Events: a nudge when the queue changes, never the queue itself.

    SSE rather than WebSockets because the traffic is one-directional, it reconnects on
    its own, and it needs no upgrade handshake to survive the proxies in front of Cloud
    Run.

    **It streams a version marker, not content.** A client that receives one re-fetches
    through the ordinary endpoint, which means a dropped, delayed or partially delivered
    stream can never put wrong data on a screen -- the worst case is a refresh that does
    not happen, and the client is still whole.
    """
    _, tenant = who
    return StreamingResponse(
        event_stream(tenant, request.is_disconnected),
        media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


async def event_stream(tenant: str, is_disconnected, interval: float = 3.0):
    """The stream itself, with the disconnect check injected.

    Separated from the route so it can be driven directly by a test. An endless generator
    behind an HTTP client is awkward to test and easy to leave half-tested, and the
    property worth pinning -- that content never crosses this wire -- is a property of
    this function rather than of the transport around it.
    """
    last = None
    # Tell the client the retry interval up front, so a disconnect is handled by the
    # browser rather than by anything we have to write.
    yield "retry: 5000\n\n"
    while not await is_disconnected():
        current = queue_version(tenant)
        if current != last:
            last = current
            yield f"event: queue\ndata: {json.dumps({'version': current})}\n\n"
        else:
            yield ": keep-alive\n\n"
        await asyncio.sleep(interval)


# ----------------------------------------------------------------------- uploads

@app.post("/v1/documents")
async def upload(file: UploadFile = File(...), who=Depends(session)) -> dict:
    """Accept a PDF and run it through the same pipeline Eventarc drives.

    One pipeline, not a second one for things a person uploaded: `ingest/pipeline.py` is
    the path, so an uploaded document gets the same grounding, the same origin check and
    the same gate as one that arrived in a bucket.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="only PDF files are accepted")

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"that file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
    if not payload.startswith(b"%PDF-"):
        # The extension is the caller's claim; this is the file's own answer.
        raise HTTPException(status_code=415, detail="that file is not a PDF")

    from ingest import pipeline

    doc_id = Path(file.filename).stem
    outcome = pipeline.process(payload, doc_id)
    return {"doc_id": outcome.doc_id, "action": outcome.action, "codes": outcome.codes,
            "spans": outcome.spans, "error": outcome.error}


# ----------------------------------------------------------------------- health

@app.get("/v1/health")
async def health() -> dict:
    return {"ok": True, "transport": "fastapi", "started": int(time.time())}


# ----------------------------------------------------------------------- running it

def run(host: str = "127.0.0.1", port: int = 8000, **kwargs) -> None:
    """Serve the app with the settings that keep the security tests true.

    `server_header=False` is the load-bearing one and it is why this function exists
    rather than a bare `uvicorn dashboard.asgi:app` in the Makefile. The middleware sets
    `Server: praetor`, but uvicorn emits its own `Server: uvicorn` at the protocol layer
    underneath it, so the response carried BOTH and advertised the server after all --
    `dashboard/serve.py` has a test forbidding exactly that, and it was silently untrue
    on this transport. A safe default beats a flag somebody has to remember.
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port, server_header=False, **kwargs)


if __name__ == "__main__":
    import os

    run(host=os.environ.get("PRAETOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")))
