"""Check the InsForge access token sent by the frontend.

The frontend signs in with the InsForge SDK and sends its access token as
`Authorization: Bearer <token>`. We ask InsForge who the token belongs to.
"""

from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException
from loguru import logger

from app.core.config import get_settings


@dataclass
class AuthUser:
    id: str
    email: str | None
    token: str  # passed on to InsForge so database writes run as this user


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:].strip() or None


def verify_token(token: str) -> AuthUser:
    """Return the user for this token, or raise HTTPException (401 or 503)."""
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.insforge_base_url.rstrip('/')}/api/auth/sessions/current",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.insforge_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        logger.error("Could not reach InsForge to verify the session: {}", exc.__class__.__name__)
        raise HTTPException(status_code=503, detail="Could not reach InsForge to verify your session.") from exc

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    if response.status_code != 200:
        logger.error("InsForge session check returned HTTP {}", response.status_code)
        raise HTTPException(status_code=503, detail="InsForge could not verify your session.")

    user = (response.json() or {}).get("user") or {}
    if not user.get("id") or user.get("role") == "anon":
        raise HTTPException(status_code=401, detail="Please sign in.")
    return AuthUser(id=user["id"], email=user.get("email"), token=token)


def current_user(authorization: str | None = Header(default=None)) -> AuthUser | None:
    """FastAPI dependency: the signed-in user, or None when auth is turned off."""
    settings = get_settings()
    token = _bearer_token(authorization)

    if not settings.auth_required and (token is None or not settings.insforge_base_url):
        return None  # local testing without sign-in
    if not settings.insforge_base_url:
        raise HTTPException(status_code=500, detail="INSFORGE_BASE_URL is not configured on the backend.")
    if token is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return verify_token(token)
