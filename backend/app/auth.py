"""Who is calling. Every endpoint except the health check needs an Amazon Cognito ID token, and the reviewer's name and role come from that token.

The role is a Cognito group (adjuster or senior). It is never read from a request body, so a caller cannot promote themselves by editing JSON. The token is
checked for signature (against the user pool's published keys), issuer, audience, expiry and token type.

Without a user pool configured (local development and CI) the API is open and takes a demo identity from headers; live mode refuses to start in that state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import jwt
from fastapi import HTTPException, Request

from app.config import settings

Role = Literal["adjuster", "senior"]
_FILES = re.compile(r"^/api/claims/[^/]+/files/[^/]+$")
OPEN_PATHS = {"/api/health"}  # the load balancer health check carries no token


@dataclass(frozen=True)
class Identity:
    username: str
    role: Role


def enabled() -> bool:
    return bool(settings.cognito_user_pool_id and settings.cognito_client_id)


def issuer() -> str:
    return f"https://cognito-idp.{settings.region}.amazonaws.com/{settings.cognito_user_pool_id}"


def check_startup() -> None:
    """Live mode spends real money and writes real decisions, so it never runs without sign-in."""
    if settings.mode == "live" and not enabled():
        raise RuntimeError("live mode needs sign-in: set CLAIMS_COGNITO_USER_POOL_ID and CLAIMS_COGNITO_CLIENT_ID")


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer()}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def _signing_key(token: str):
    return _jwks().get_signing_key_from_jwt(token).key


def _plain_name(raw: str) -> str:
    """A name safe to store in the audit log: letters, digits and a few separators, at most 60 characters."""
    return re.sub(r"[^A-Za-z0-9 ._@-]", "", raw).strip()[:60] or "user"


def verify(token: str) -> Identity:
    """Return who the token belongs to, or raise HTTPException(401 or 403)."""
    try:
        claims = jwt.decode(token, _signing_key(token), algorithms=["RS256"], audience=settings.cognito_client_id, issuer=issuer(),
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "sign in again: the token is missing, expired or not valid", headers={"WWW-Authenticate": "Bearer"}) from None
    except Exception:  # the key set could not be fetched or the token is not even parseable: refuse, never allow
        raise HTTPException(401, "sign in again: the token could not be checked", headers={"WWW-Authenticate": "Bearer"}) from None
    if claims.get("token_use") != "id":
        raise HTTPException(401, "an ID token is required", headers={"WWW-Authenticate": "Bearer"})
    groups = claims.get("cognito:groups") or []
    role: Role | None = "senior" if "senior" in groups else "adjuster" if "adjuster" in groups else None
    if role is None:
        raise HTTPException(403, "your account is not in the adjuster or senior adjuster group")
    return Identity(_plain_name(str(claims.get("cognito:username") or claims.get("email") or claims["sub"])), role)


def _token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # An <img> or <a> tag cannot send a header, so the read-only file endpoint also accepts the token from a same-site cookie. Nothing that changes state does.
    if request.method == "GET" and _FILES.match(request.url.path):
        return request.cookies.get("claims_token")
    return None


def authenticate(request: Request) -> Identity | None:
    """FastAPI dependency applied to the whole app. Returns the caller, or None for the open health check."""
    if request.url.path in OPEN_PATHS or request.method == "OPTIONS":
        return None
    if not enabled():
        role = request.headers.get("x-demo-role", "adjuster")
        return Identity(_plain_name(request.headers.get("x-demo-user", "local-dev")), "senior" if role == "senior" else "adjuster")
    token = _token(request)
    if not token:
        raise HTTPException(401, "sign in to use this API", headers={"WWW-Authenticate": "Bearer"})
    return verify(token)
