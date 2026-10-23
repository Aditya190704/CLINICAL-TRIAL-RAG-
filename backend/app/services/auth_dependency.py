"""FastAPI dependency for Firebase-authenticated requests."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.firebase_auth import verify_firebase_id_token

_bearer = HTTPBearer(auto_error=False)


async def require_firebase_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="A Firebase sign-in is required.")
    try:
        claims = await asyncio.to_thread(verify_firebase_id_token, credentials.credentials)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Firebase authentication is not configured on the server.") from exc
    except Exception as exc:
        # Provider failures are deliberately not returned to callers. Missing
        # or invalid credentials must never fall through as an anonymous user.
        raise HTTPException(status_code=401, detail="The Firebase ID token is invalid or expired.") from exc
    uid = claims.get("uid") or claims.get("sub")
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", uid):
        raise HTTPException(status_code=401, detail="The Firebase ID token has no valid user identity.")
    return {
        "uid": uid,
        "email": str(claims.get("email") or ""),
        "display_name": str(claims.get("name") or ""),
    }
