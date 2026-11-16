"""Per-client rate limits for the API, so the free pages stay open without being scraped flat.

A client is its API key when it sends one (partners, scripts), otherwise its IP address
(website visitors; the page's own key is added later, on the server, so it never counts here).
Each client gets a token bucket per rule: a burst of `limit` requests, refilled evenly over
`period` seconds. Over the limit the answer is 429 with Retry-After.

The buckets live in this process. One app instance is fine; with several replicas each keeps its
own count (so the real limit is N times higher) until this moves to a shared store such as Redis.

Tune with environment variables (requests per minute): RATE_LIMIT_API, RATE_LIMIT_UNITS,
RATE_LIMIT_KEYED; waitlist sign-ups per 10 minutes: RATE_LIMIT_WAITLIST.
"""
import hashlib
import json
import os
import re
import time

UNITS = re.compile(r"^(/api)?/v1/projects/[^/]+/units")


def _env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RateLimit:
    def __init__(self, inner):
        self.inner = inner
        self.rules = {
            # (requests, seconds)
            "waitlist": (_env("RATE_LIMIT_WAITLIST", 5), 600),    # sign-ups: a person, not a bot
            "units": (_env("RATE_LIMIT_UNITS", 30), 60),          # flat-by-flat prices: the heaviest data
            "keyed": (_env("RATE_LIMIT_KEYED", 600), 60),         # partners with their own key
            "api": (_env("RATE_LIMIT_API", 240), 60),             # the free website and its map
        }
        self.buckets: dict[tuple, list] = {}
        self.swept = time.monotonic()

    def rule_for(self, method: str, path: str, keyed: bool) -> str | None:
        if not (path.startswith("/api/") or path.startswith("/v1/")):
            return None  # the page, its assets, /health and /docs are not limited
        if method == "POST" and path.rstrip("/").endswith("/v1/waitlist"):
            return "waitlist"
        if UNITS.match(path):
            return "units"
        return "keyed" if keyed else "api"

    def take(self, rule: str, client: str) -> float:
        """Spend one token. Returns 0 when allowed, else seconds until the next token."""
        limit, period = self.rules[rule]
        now = time.monotonic()
        key = (rule, client)
        tokens, last = self.buckets.get(key, (float(limit), now))
        tokens = min(limit, tokens + (now - last) * limit / period)
        if tokens >= 1:
            self.buckets[key] = [tokens - 1, now]
            wait = 0.0
        else:
            self.buckets[key] = [tokens, now]
            wait = (1 - tokens) * period / limit
        if now - self.swept > 300:  # forget clients idle for a while, so memory stays small
            self.swept = now
            cutoff = now - 900
            self.buckets = {k: v for k, v in self.buckets.items() if v[1] > cutoff}
        return wait

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = dict(scope["headers"])
        api_key = headers.get(b"x-api-key")
        rule = self.rule_for(scope["method"], scope["path"], bool(api_key))
        if rule is None:
            return await self.inner(scope, receive, send)
        # Keys are counted by a hash, so the bucket table never holds a usable key.
        client = ("key:" + hashlib.sha256(api_key).hexdigest()[:16]) if api_key else \
                 ("ip:" + ((scope.get("client") or ("unknown",))[0]))
        wait = self.take(rule, client)
        if not wait:
            return await self.inner(scope, receive, send)
        retry = max(1, round(wait))
        body = json.dumps({"detail": f"Too many requests. Try again in {retry} s."}).encode()
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"retry-after", str(retry).encode()),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
