"""In-memory token-bucket rate limiter keyed by user or IP address."""

import time


class RateLimiter:
    def __init__(self, rate=5.0, capacity=10.0, clock=time.monotonic, max_keys=4096):
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.clock = clock
        self.max_keys = max_keys
        self._buckets = {}

    def allow(self, key, cost=1.0):
        now = self.clock()
        tokens, updated = self._buckets.get(key, (self.capacity, now))
        elapsed = max(0.0, now - updated)
        tokens = min(self.capacity, tokens + elapsed * self.rate)
        if tokens < cost:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - cost, now)
        if len(self._buckets) > self.max_keys:
            self._prune(now)
        return True

    def _prune(self, now):
        cutoff = now - (self.capacity / max(self.rate, 0.001)) * 2
        stale = [k for k, (_, ts) in self._buckets.items() if ts < cutoff]
        for k in stale:
            self._buckets.pop(k, None)

