"""The limiter on the endpoints a stranger can reach.

`/v1/gauntlet/run` is open on purpose and was unmetered by accident. On Cloud Run that
combination has a specific, unpleasant ending: CPU is billed per request, enough requests
trip the ₹300 spend cap, the cap pauses the service, and the control that protects the
card is what takes the demo offline — for up to an hour, by hand.

These tests pin the behaviour that matters rather than the exact numbers, so the limits
can be tuned without rewriting the suite.
"""
import time

import pytest

from dashboard.ratelimit import RateLimiter, caller_key


class _Headers(dict):
    def get(self, k, default=None):          # match the http.server headers interface
        return dict.get(self, k, default)


def test_a_caller_is_allowed_up_to_the_limit_then_refused():
    rl = RateLimiter(limit=3, window=60.0, global_limit=100)
    assert [rl.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, retry = rl.check("a")
    assert allowed is False
    assert 1 <= retry <= 61


def test_callers_do_not_share_a_budget():
    rl = RateLimiter(limit=2, window=60.0, global_limit=100)
    rl.check("a"); rl.check("a")
    assert rl.check("a")[0] is False
    assert rl.check("b")[0] is True, "one caller must not lock out everyone else"


def test_the_window_slides():
    rl = RateLimiter(limit=2, window=10.0, global_limit=100)
    rl.check("a", now=0.0)
    rl.check("a", now=1.0)
    assert rl.check("a", now=2.0)[0] is False
    assert rl.check("a", now=11.5)[0] is True, "the first hit should have aged out"


def test_a_refused_request_does_not_extend_the_lockout():
    """Hammering a closed door must not keep pushing the window forward. Otherwise a
    client retrying in a loop locks itself out indefinitely and it looks like a bug."""
    rl = RateLimiter(limit=1, window=10.0, global_limit=100)
    rl.check("a", now=0.0)
    for t in (1.0, 2.0, 3.0, 4.0):
        assert rl.check("a", now=t)[0] is False
    assert rl.check("a", now=10.5)[0] is True


def test_the_global_ceiling_catches_a_rotating_key():
    """The per-caller key comes from a header a client can partly control, so it cannot
    be the only defence. This is why the ceiling exists."""
    rl = RateLimiter(limit=100, window=60.0, global_limit=5)
    allowed = [rl.check(f"caller-{i}")[0] for i in range(8)]
    assert allowed.count(True) == 5
    assert allowed[-1] is False


def test_the_limiter_cannot_grow_without_bound():
    """A caller rotating keys must not turn the defence into a memory leak."""
    rl = RateLimiter(limit=5, window=60.0, global_limit=10_000, max_keys=32)
    for i in range(500):
        rl.check(f"caller-{i}")
    assert len(rl._hits) <= 32


def test_it_is_safe_under_concurrent_requests():
    """The server is threaded, so two requests really do arrive at once. The count must
    not exceed the limit no matter how they interleave."""
    import threading
    rl = RateLimiter(limit=50, window=60.0, global_limit=10_000)
    granted = []
    lock = threading.Lock()

    def hammer():
        for _ in range(40):
            ok, _ = rl.check("shared")
            if ok:
                with lock:
                    granted.append(1)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(granted) == 50, "the limit must hold exactly under contention"


# ------------------------------------------------------------------ identifying callers

def test_the_caller_comes_from_the_proxy_header_on_cloud_run():
    h = _Headers({"X-Forwarded-For": "203.0.113.7, 130.211.0.1"})
    assert caller_key(h, ("10.0.0.1", 1234)) == "203.0.113.7"


def test_it_falls_back_to_the_socket_when_there_is_no_proxy():
    assert caller_key(_Headers({}), ("198.51.100.4", 5678)) == "198.51.100.4"


def test_a_missing_address_still_produces_a_key():
    """No key means no limiting, so this must never return empty."""
    assert caller_key(_Headers({}), None)
    assert caller_key(_Headers({"X-Forwarded-For": "  ,  "}), ("1.2.3.4", 1))


def test_an_enormous_header_cannot_blow_up_the_key_space():
    h = _Headers({"X-Forwarded-For": "x" * 10_000})
    assert len(caller_key(h, ("1.2.3.4", 1))) <= 64
