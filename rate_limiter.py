"""
rate_limiter.py — Fixed-window rate limiting, per client.

Kept dependency-free (no Flask-Limiter/Redis) so the whole project runs
with just `flask` installed. Swap the in-memory store for Redis in
production if running multiple processes/instances, since this
implementation's state does not share across workers.
"""

import time
from threading import Lock
from functools import wraps
from flask import request, jsonify

_lock = Lock()
_buckets = {}  # client_id -> {"window_start": ts, "count": int}

DEFAULT_LIMIT = 30          # requests
DEFAULT_WINDOW_SECONDS = 60  # per this many seconds


def _get_client_id() -> str:
    # In production this would be an API key. For this project, we fall
    # back to the request's IP if no key header is present.
    return request.headers.get("X-Api-Key") or request.remote_addr or "anonymous"


def check_rate_limit(client_id: str, limit: int = DEFAULT_LIMIT,
                      window_seconds: int = DEFAULT_WINDOW_SECONDS) -> dict:
    now = time.time()
    with _lock:
        bucket = _buckets.get(client_id)
        if bucket is None or (now - bucket["window_start"]) >= window_seconds:
            _buckets[client_id] = {"window_start": now, "count": 1}
            remaining = limit - 1
            allowed = True
        else:
            bucket["count"] += 1
            remaining = limit - bucket["count"]
            allowed = bucket["count"] <= limit

        reset_in = window_seconds - (now - _buckets[client_id]["window_start"])

    return {
        "allowed": allowed,
        "remaining": max(remaining, 0),
        "limit": limit,
        "reset_in_seconds": round(max(reset_in, 0), 1),
    }


def rate_limited(limit: int = DEFAULT_LIMIT, window_seconds: int = DEFAULT_WINDOW_SECONDS):
    """Flask route decorator enforcing a per-client rate limit."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            client_id = _get_client_id()
            result = check_rate_limit(client_id, limit, window_seconds)
            if not result["allowed"]:
                response = jsonify({
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit of {limit} requests per {window_seconds}s exceeded.",
                    "retry_after_seconds": result["reset_in_seconds"],
                })
                response.status_code = 429
                response.headers["Retry-After"] = str(int(result["reset_in_seconds"]))
                return response

            response = fn(*args, **kwargs)
            # Attach rate-limit headers to successful responses too.
            try:
                response.headers["X-RateLimit-Limit"] = str(result["limit"])
                response.headers["X-RateLimit-Remaining"] = str(result["remaining"])
            except AttributeError:
                pass
            return response
        return wrapper
    return decorator
