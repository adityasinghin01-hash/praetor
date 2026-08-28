"""What the web layer does for someone who is not signed in, or should not be trusted.

`praetor/auth.py` was already sound — PBKDF2 with a per-password salt, constant-time
comparison, session tokens stored hashed. The gaps were all *around* it: nothing stopped
an unlimited number of password guesses, no response carried a single security header,
and the sign-in page printed the password next to the form it opens, on a public URL.

These run a real server on a real socket. Asserting on a handler in isolation would not
have caught the thing that actually mattered — that headers were missing from every
response — because the bug was the absence of a call, not the wrongness of one.
"""
import http.client
import os
import threading
from http.server import ThreadingHTTPServer

import pytest

from dashboard import serve


@pytest.fixture
def server():
    """A real server on a real port, torn down after each test."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def _get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, dict(r.getheaders()), body


def _post(port, path, body=b"", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, body=body,
              headers={"Content-Type": "application/json", **(headers or {})})
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, dict(r.getheaders()), out


@pytest.fixture(autouse=True)
def fresh_limiters(monkeypatch):
    """Limiters are process-wide, so tests would otherwise poison each other."""
    from dashboard import ratelimit
    monkeypatch.setattr(serve, "LOGIN_LIMIT",
                        ratelimit.RateLimiter(limit=10, window=300.0, global_limit=60))
    monkeypatch.setattr(serve, "RUN_LIMIT",
                        ratelimit.RateLimiter(limit=20, window=60.0, global_limit=120))
    monkeypatch.setattr(serve, "READ_LIMIT",
                        ratelimit.RateLimiter(limit=120, window=60.0, global_limit=600))


# ------------------------------------------------------------------- security headers

@pytest.mark.parametrize("header,expected", [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
])
def test_every_response_carries_the_security_headers(server, header, expected):
    _, headers, _ = _get(server, "/login")
    assert headers.get(header) == expected


def test_clickjacking_is_refused_two_ways(server):
    """There is an Approve button here that moves money. Framing it is a real attack."""
    _, headers, _ = _get(server, "/login")
    assert headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")


def test_the_json_api_is_covered_too(server):
    """The headers were added in one place on purpose, so no route can be forgotten."""
    _, headers, _ = _get(server, "/v1/gauntlet/examples")
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("Cache-Control") == "no-store"


def test_the_interpreter_version_is_not_advertised(server):
    _, headers, _ = _get(server, "/login")
    assert "Python" not in headers.get("Server", "")


def test_hsts_only_when_the_connection_really_was_https(server):
    _, plain, _ = _get(server, "/login")
    assert "Strict-Transport-Security" not in plain
    _, secure, _ = _get(server, "/login", {"X-Forwarded-Proto": "https"})
    assert "max-age=" in secure.get("Strict-Transport-Security", "")


# --------------------------------------------------------------- the demo password

def test_the_demo_password_is_shown_when_you_run_it_yourself(server, monkeypatch):
    """DECISIONS.md #11: a judge cloning the repo has no other way in."""
    monkeypatch.delenv("K_SERVICE", raising=False)
    _, _, body = _get(server, "/login")
    assert b"Seeded demo accounts" in body


def test_the_demo_password_is_never_shown_on_a_deployed_url(server, monkeypatch):
    """Cloud Run sets K_SERVICE. A credential printed beside the form it opens is
    indefensible however synthetic the data behind it is."""
    monkeypatch.setenv("K_SERVICE", "praetor")
    _, _, body = _get(server, "/login")
    assert b"Seeded demo accounts" not in body
    assert b"password <code>" not in body


# -------------------------------------------------------------------- rate limiting

def test_password_guessing_is_bounded(server):
    """PBKDF2 makes each guess expensive for us as well as for the attacker, so an
    unmetered form is both a brute-force surface and a way to burn our own CPU."""
    codes = [_post(server, "/login", b"email=a@b.c&password=wrong",
                   {"Content-Type": "application/x-www-form-urlencoded"})[0]
             for _ in range(14)]
    assert 429 in codes, "sign-in must not accept unlimited guesses"
    assert codes.count(429) >= 3


def test_the_anonymous_pipeline_endpoint_is_bounded(server):
    """It runs real work and writes to disk for anyone who asks."""
    body = b'{"doc_id": "V000_003", "text": "test"}'
    codes = [_post(server, "/v1/gauntlet/run", body)[0] for _ in range(25)]
    assert codes.count(200) <= 20
    assert 429 in codes


def test_a_refusal_tells_the_caller_when_to_come_back(server):
    body = b'{"doc_id": "V000_003", "text": "test"}'
    last = None
    for _ in range(25):
        last = _post(server, "/v1/gauntlet/run", body)
    status, headers, out = last
    assert status == 429
    assert int(headers["Retry-After"]) >= 1
    assert b"Too many attempts" in out
    assert b"rate" not in out.lower(), "say it in plain language, not in ours"


# ------------------------------------------------------------------------- authz

def test_client_data_needs_a_session(server):
    for path in ("/v1/queue", "/v1/stopped", "/v1/notes?doc_id=x"):
        status, _, _ = _get(server, path)
        assert status == 401, path


def test_writing_a_note_needs_a_session(server):
    status, _, _ = _post(server, "/v1/notes", b'{"doc_id": "x", "body": "y"}')
    assert status == 401


def test_an_unknown_route_is_not_a_way_in(server):
    for path in ("/v1/", "/v1/nope", "/../etc/passwd"):
        status, _, _ = _get(server, path)
        assert status in (401, 404), path
