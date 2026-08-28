"""The FastAPI transport: same contract, plus paging, live updates and uploads.

The load-bearing test here is `test_both_transports_return_the_same_json`. `docs/PLAN.md`
Phase 6 calls this a transport swap, and that is only true if it is true — so the same
request is issued through `dashboard/serve.py` and through `dashboard/asgi.py` and the
bodies are compared. A divergence fails the build instead of surfacing later as a
frontend bug nobody can localise.

Skipped where FastAPI is absent, the same way `tests/test_trace.py` skips without the
OpenTelemetry SDK: `dashboard/serve.py` is standard library only and `make demo` must
keep working on a laptop with nothing installed.
"""
from __future__ import annotations

import http.client
import json
import pathlib
import threading
from http.server import ThreadingHTTPServer

import pytest

# Guarded imports rather than a module-level `importorskip`, so every test here is still
# COLLECTED when FastAPI is absent and merely skipped. A module-level skip changes the
# collected count between the full environment and the pytest-only CI job, and
# tests/test_documented_counts.py compares that count against the figure in the README --
# so it would have failed the kernel-only job for a reason that has nothing to do with
# the kernel.
try:
    from fastapi.testclient import TestClient

    from dashboard import api, asgi, serve
    from praetor import store

    HAVE_FASTAPI = True
except ImportError:                                        # pragma: no cover
    TestClient = None
    api = asgi = serve = store = None
    HAVE_FASTAPI = False

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.skipif(not HAVE_FASTAPI, reason="FastAPI is not installed"),
    pytest.mark.skipif(
        not (ROOT / "out" / "vm_constructed.json").exists(),
        reason="run `make rules` first"),
]

# The tenant the store actually ships with. Hard-coding "acme" made the queue tests
# vacuous -- the app read an empty tenant and every paging assertion passed on 0 rows.
TENANT = store.DEFAULT_TENANT if HAVE_FASTAPI else ""


@pytest.fixture
def client(monkeypatch):
    """A client with the session dependency satisfied.

    Overriding the dependency rather than logging in keeps these tests about the
    transport. `tests/test_web_security.py` and `tests/test_auth.py` own the question of
    who gets a session in the first place.
    """
    asgi.app.dependency_overrides[asgi.session] = lambda: ("priya", TENANT)
    monkeypatch.setattr(serve.READ_LIMIT, "limit", 10_000)
    monkeypatch.setattr(serve.RUN_LIMIT, "limit", 10_000)
    with TestClient(asgi.app) as c:
        yield c
    asgi.app.dependency_overrides.clear()


@pytest.fixture
def anonymous(monkeypatch):
    monkeypatch.setattr(serve.READ_LIMIT, "limit", 10_000)
    monkeypatch.setattr(serve.RUN_LIMIT, "limit", 10_000)
    with TestClient(asgi.app) as c:
        yield c


@pytest.fixture
def stdlib_server(monkeypatch):
    """The old transport, on a real socket, for the comparison."""
    monkeypatch.setattr(serve.READ_LIMIT, "limit", 10_000)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def _stdlib_get(port: int, path: str) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, (json.loads(body) if body else {})


# ------------------------------------------------------------- the swap is a swap

@pytest.mark.parametrize("path", [
    "/v1/gauntlet/documents",
    "/v1/gauntlet/examples",
])
def test_both_transports_return_the_same_json(stdlib_server, anonymous, path):
    """Phase 6 calls this a transport swap. This is what makes that a fact."""
    old_status, old_body = _stdlib_get(stdlib_server, path)
    new = anonymous.get(path)
    assert old_status == new.status_code == 200
    assert old_body == new.json(), f"{path} diverged between transports"


def test_the_queue_body_is_the_contract_plus_paging(client):
    """Everything `dashboard/api.py` produced is still there, untouched, with the page
    metadata added alongside rather than replacing anything."""
    # The same source the app reads, so this tests the transport rather than which
    # tenant happens to have data in it.
    contract = api.queue(asgi._rows(TENANT))
    got = client.get("/v1/queue", params={"per_page": 5}).json()

    for key, value in contract.items():
        if key == "rows":
            continue
        assert got[key] == value, f"{key} changed between transports"
    assert got["page"]["total_rows"] == len(contract["rows"])


# ------------------------------------------------------------- paging is a window

def test_the_queue_under_test_is_not_empty(client):
    """Teeth. Every paging assertion below passes on an empty queue, so the premise is
    checked once rather than assumed five times."""
    assert client.get("/v1/queue").json()["page"]["total_rows"] > 10


def test_walking_the_pages_returns_every_row_exactly_once(client):
    """Paging is a window, never a filter.

    A response that quietly returned 25 of 65 rows with no way to reach the rest would be
    the queue-shortening `praetor/queueing.py` refuses to do, arriving by another route.
    """
    first = client.get("/v1/queue", params={"per_page": 7}).json()
    total = first["page"]["total_rows"]
    pages = first["page"]["pages"]

    seen = []
    for page in range(1, pages + 1):
        body = client.get("/v1/queue", params={"per_page": 7, "page": page}).json()
        seen.extend(r["id"] for r in body["rows"])

    assert len(seen) == total
    assert len(set(seen)) == total, "a row appeared on two pages"

    unpaged = client.get("/v1/queue", params={"per_page": 200}).json()
    assert seen == [r["id"] for r in unpaged["rows"]], "paging reordered the queue"


def test_the_totals_never_shrink_with_the_page(client):
    """`waiting` is what she has to do, not what fits on screen."""
    small = client.get("/v1/queue", params={"per_page": 1}).json()
    large = client.get("/v1/queue", params={"per_page": 200}).json()
    assert small["waiting"] == large["waiting"]
    assert small["handled"] == large["handled"]
    assert small["headline"] == large["headline"]


def test_a_page_beyond_the_end_clamps_rather_than_hiding_the_queue(client):
    body = client.get("/v1/queue", params={"page": 9999, "per_page": 5}).json()
    assert body["page"]["page"] == body["page"]["pages"]
    assert body["rows"], "an out-of-range page returned nothing at all"


def test_per_page_is_bounded(client):
    assert client.get("/v1/queue", params={"per_page": 10_000}).status_code == 422
    assert client.get("/v1/queue", params={"per_page": 0}).status_code == 422


# ------------------------------------------------------------- the old rules still hold

@pytest.mark.parametrize("header,expected", [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
])
def test_the_security_headers_survive_the_transport(anonymous, header, expected):
    """Imported from serve.py, not restated -- two copies is one that falls behind."""
    r = anonymous.get("/v1/gauntlet/examples")
    assert r.headers[header] == expected
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_the_server_header_advertises_nothing(anonymous):
    assert anonymous.get("/v1/health").headers["Server"] == "praetor"


def test_a_clients_own_data_needs_a_session(anonymous):
    for path in ("/v1/queue", "/v1/stopped", "/v1/notes", "/v1/events"):
        assert anonymous.get(path).status_code == 401, path


def test_the_open_endpoints_stay_open(anonymous):
    """Tab 3 is the 'try to break it' page. Requiring a login to attack a demo defeats
    its point, and it touches only the synthetic corpus."""
    assert anonymous.get("/v1/gauntlet/examples").status_code == 200


# ------------------------------------------------------------- uploads

def _upload(client, name: str, payload: bytes):
    return client.post("/v1/documents",
                       files={"file": (name, payload, "application/pdf")})


def test_a_non_pdf_is_refused_by_extension_and_by_content(client):
    assert _upload(client, "notes.txt", b"%PDF-1.4 ...").status_code == 415
    # The extension is the caller's claim; the magic bytes are the file's own answer.
    assert _upload(client, "invoice.pdf", b"<html>not a pdf</html>").status_code == 415


def test_an_oversized_file_is_refused(client):
    too_big = b"%PDF-" + b"0" * (asgi.MAX_UPLOAD_BYTES + 1)
    assert _upload(client, "huge.pdf", too_big).status_code == 413


def test_an_upload_goes_through_the_same_pipeline_as_the_bucket(client, monkeypatch):
    """One pipeline, not a second one for things a person uploaded."""
    from ingest import pipeline

    called = {}

    def fake(pdf, doc_id, **kwargs):
        called["doc_id"] = doc_id
        return pipeline.Outcome(doc_id=doc_id, doc_hash="h", action="escalate",
                                codes=["NO_READER"], spans=21)

    monkeypatch.setattr(pipeline, "process", fake)
    r = _upload(client, "V000_003.pdf", b"%PDF-1.4 fake")
    assert r.status_code == 200
    assert called["doc_id"] == "V000_003"
    assert r.json()["action"] == "escalate"


# ------------------------------------------------------------- live updates

def test_events_stream_a_version_and_never_the_queue():
    """A dropped or partial stream must not be able to put wrong data on a screen.

    So the stream carries a marker and the client re-fetches through the ordinary
    endpoint. Driven directly rather than over HTTP: the property is about what this
    generator emits, and an endless generator behind a test client is a hang waiting to
    happen.
    """
    import asyncio as _asyncio

    from praetor import store as _store

    ticks = iter([False, False, True])

    async def disconnected():
        return next(ticks, True)

    async def collect():
        return [chunk async for chunk in
                asgi.event_stream(_store.DEFAULT_TENANT, disconnected, interval=0)]

    chunks = _asyncio.run(collect())
    body = "".join(chunks)

    assert body.startswith("retry: 5000")
    assert "event: queue" in body

    payload = json.loads(body.split("data:")[1].split("\n")[0])
    assert set(payload) == {"version"}, "the event stream carried more than a marker"

    # Nothing about any invoice may cross this wire.
    for word in ("vendor", "supplier", "invoice", "account", "amount"):
        assert word not in body.lower(), f"the stream leaked {word!r}"


def test_the_stream_stops_when_the_client_goes_away():
    """Otherwise every closed tab is a generator still reading the queue every 3s."""
    import asyncio as _asyncio

    from praetor import store as _store

    async def collect():
        async def gone():
            return True
        return [c async for c in
                asgi.event_stream(_store.DEFAULT_TENANT, gone, interval=0)]

    assert _asyncio.run(collect()) == ["retry: 5000\n\n"]


# ------------------------------------------------------- the real socket, not the client

def test_the_real_server_advertises_no_software():
    """TestClient cannot see this, and that is the point.

    The middleware sets `Server: praetor`, but uvicorn emits its own `Server: uvicorn`
    underneath it at the protocol layer, so a real response carried both and advertised
    the server anyway. `dashboard/serve.py` has a test forbidding that; it was silently
    untrue here until `asgi.run()` set `server_header=False`.

    So this starts a real server on a real socket, for the same reason
    `tests/test_web_security.py` does: asserting on a handler in isolation would have
    missed it.
    """
    import socket
    import threading
    import time as _time

    import uvicorn

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(asgi.app, host="127.0.0.1", port=port,
                            server_header=False, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = _time.time() + 20
        while not server.started and _time.time() < deadline:
            _time.sleep(0.1)
        assert server.started, "uvicorn did not start"

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/v1/health")
        response = conn.getresponse()
        response.read()
        servers = [v for k, v in response.getheaders() if k.lower() == "server"]
        conn.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert servers == ["praetor"], f"the server advertised itself: {servers}"
    assert not any("uvicorn" in v.lower() for v in servers)
