from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class Rule:
    key: str
    per_minute: int


_LOCK = threading.Lock()
_BUCKETS: Dict[Tuple[str, str], Deque[float]] = {}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, value)


def _client_ip(request: Request) -> str:
    # For typical local/LAN usage, request.client.host is fine.
    # If you ever run behind a reverse proxy, set TRUST_PROXY=1 to honor X-Forwarded-For.
    if os.environ.get("TRUST_PROXY") == "1":
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune_and_count(bucket: Deque[float], now: float, window_seconds: float) -> int:
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return len(bucket)


def _check(rule: Rule, ip: str, now: float) -> bool:
    if rule.per_minute <= 0:
        return True  # disabled
    window = 60.0
    key = (rule.key, ip)
    with _LOCK:
        bucket = _BUCKETS.get(key)
        if bucket is None:
            bucket = deque()
            _BUCKETS[key] = bucket
        count = _prune_and_count(bucket, now, window)
        if count >= rule.per_minute:
            return False
        bucket.append(now)
        return True


def _rate_limited(rule: Rule) -> Response:
    return JSONResponse(
        {
            "error": "rate_limited",
            "message": f"Too many requests for {rule.key}. Please slow down.",
        },
        status_code=429,
        headers={"Retry-After": "60"},
    )


async def rate_limit_middleware(request: Request, call_next):
    chat_limit = _env_int("RATE_LIMIT_CHAT_PER_MIN", 20)
    video_limit = _env_int("RATE_LIMIT_VIDEO_PER_MIN", 5)

    path = request.url.path
    method = request.method.upper()

    rule = None
    if path == "/chat" and method == "POST":
        rule = Rule("chat", chat_limit)
    elif path == "/video_feed" and method == "GET":
        rule = Rule("video_feed", video_limit)

    if rule is not None:
        now = time.time()
        ip = _client_ip(request)
        if not _check(rule, ip, now):
            return _rate_limited(rule)

    return await call_next(request)
