from __future__ import annotations

import secrets

from fastapi import Header, Request

from app.errors import AuthenticationError


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.api_key
    candidate = x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()

    if not candidate or not secrets.compare_digest(candidate, expected):
        raise AuthenticationError("invalid or missing API key")
