from __future__ import annotations

import base64
import os
import secrets
from typing import Optional, Tuple

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


def _get_basic_credentials_from_env() -> Optional[Tuple[str, str]]:
    user = os.environ.get("BASIC_AUTH_USER")
    password = os.environ.get("BASIC_AUTH_PASSWORD")
    if not user or not password:
        return None
    return user, password


def _parse_basic_auth(header_value: str) -> Optional[Tuple[str, str]]:
    if not header_value:
        return None
    try:
        scheme, b64 = header_value.split(" ", 1)
    except ValueError:
        return None
    if scheme.lower() != "basic":
        return None
    try:
        raw = base64.b64decode(b64.strip()).decode("utf-8")
    except Exception:
        return None
    if ":" not in raw:
        return None
    user, password = raw.split(":", 1)
    return user, password


def _unauthorized() -> Response:
    return PlainTextResponse(
        "Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Smart Security System"'},
    )


async def basic_auth_middleware(request: Request, call_next):
    creds = _get_basic_credentials_from_env()
    if creds is None:
        return await call_next(request)  # auth disabled

    expected_user, expected_pass = creds
    parsed = _parse_basic_auth(request.headers.get("authorization", ""))
    if parsed is None:
        return _unauthorized()

    user, password = parsed
    if not (secrets.compare_digest(user, expected_user) and secrets.compare_digest(password, expected_pass)):
        return _unauthorized()

    return await call_next(request)
