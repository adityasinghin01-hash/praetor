"""Rate limiting for the endpoints a stranger can reach.

`/v1/gauntlet/run` is deliberately open — it is the "try to break it" page, and putting a
login in front of an invitation to attack a demo defeats the invitation. Open and
unmetered are different things, though, and until now it was both: an anonymous request
ran the whole pipeline and appended a line to disk, with nothing between a curious
visitor and a script in a loop.

What that actually costs, on the deployed service:

* **Cloud Run bills CPU per request.** Enough of them and the ₹300 spend cap enforces,
  the service pauses, and the demo is offline until someone lifts it by hand — up to an
  hour. The control protecting the card becomes the thing that takes the site down.
* **The attack corpus fills with noise.** It is capped at 32MB, so a loop does not fill
  the disk, but it can push the real attempts out of reach behind junk.

So: a sliding window per caller, plus a ceiling across all callers.

**The honest limits of this, stated rather than discovered later.**

1. **It is per instance, held in memory.** The service runs up to three, so a determined
   caller spread across them gets up to three times the limit. That is a real weakening
   and it is still worth having: it turns "unbounded" into "bounded by a small constant".
   Shared state would mean Firestore or Redis on the request path, which buys accuracy at
   the cost of a dependency the demo can trip over.
2. **It resets when an instance restarts.** Cloud Run scales to zero, so a quiet period
   clears the counters. Again: fine for what this defends.
3. **The caller's address comes from a header** that a client can partly control. The
   global ceiling exists precisely because the per-caller key cannot be fully trusted.

Standard library only, and thread-safe: the server is threaded, so two requests really do
arrive at once.
"""
from __future__ import annotations

import threading
import time
from collections import deque

# Per caller, per window. Generous for a person clicking Go, useless for a loop.
DEFAULT_LIMIT = 20
DEFAULT_WINDOW = 60.0

# Across every caller on this instance. The backstop for when the per-caller key is
# being rotated, spoofed, or spread over a botnet.
DEFAULT_GLOBAL = 120

# Bound on how many distinct callers we track, so the limiter cannot itself become the
# memory leak. Least-recently-seen is evicted first.
MAX_KEYS = 4096


class RateLimiter:
    """A sliding window over request timestamps."""

    def __init__(self, limit: int = DEFAULT_LIMIT, window: float = DEFAULT_WINDOW,
                 global_limit: int = DEFAULT_GLOBAL, max_keys: int = MAX_KEYS) -> None:
        self.limit = limit
        self.window = window
        self.global_limit = global_limit
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, d: deque[float], now: float) -> None:
        cutoff = now - self.window
        while d and d[0] <= cutoff:
            d.popleft()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """(allowed, retry_after_seconds). Records the hit when it is allowed.

        A refused request is not recorded, so a caller hammering a closed door does not
        keep pushing their own window forward and lock themselves out for longer than the
        window. That behaviour is confusing and looks like a bug to the person on the
        other end.
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(self._all, now)
            if len(self._all) >= self.global_limit:
                return False, self._retry_after(self._all, now)

            d = self._hits.get(key)
            if d is None:
                if len(self._hits) >= self.max_keys:
                    # Evict the key whose most recent hit is oldest.
                    oldest = min(self._hits, key=lambda k: self._hits[k][-1]
                                 if self._hits[k] else 0.0)
                    self._hits.pop(oldest, None)
                d = self._hits[key] = deque()

            self._trim(d, now)
            if len(d) >= self.limit:
                return False, self._retry_after(d, now)

            d.append(now)
            self._all.append(now)
            return True, 0

    def _retry_after(self, d: deque[float], now: float) -> int:
        if not d:
            return 1
        return max(1, int(self.window - (now - d[0])) + 1)


def caller_key(headers, client_address) -> str:
    """Who is asking, as well as we can tell behind a proxy.

    Cloud Run terminates TLS in front of the container and puts the caller's address in
    `X-Forwarded-For`. A client can prepend entries to that header, so this is a hint and
    not an identity — which is exactly why `RateLimiter` also has a global ceiling that
    does not depend on it being honest.
    """
    fwd = (headers.get("X-Forwarded-For") or "").split(",")
    first = fwd[0].strip() if fwd and fwd[0].strip() else ""
    if first:
        return first[:64]
    return str(client_address[0] if client_address else "unknown")[:64]
