"""Firebase Admin initialization and ID-token verification."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _firebase_app():
    try:
        import firebase_admin
    except ImportError as exc:
        raise RuntimeError("Firebase Admin SDK is not installed.") from exc

    try:
        return firebase_admin.get_app()
    except ValueError:
        from app.config import settings

        project_id = settings.firebase_project_id or settings.gcp_project
        options: dict[str, str] = {}
        if project_id:
            options["projectId"] = project_id
        return firebase_admin.initialize_app(options=options or None)


def verify_firebase_id_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token using ADC-backed Admin SDK credentials."""
    from firebase_admin import auth

    # Signature, issuer, audience, and expiration are still checked. Skipping
    # the revocation lookup avoids an extra network round trip on every API call.
    return auth.verify_id_token(token, app=_firebase_app(), check_revoked=False)


def firestore_client():
    """Return the Admin Firestore client; server SDK access bypasses rules."""
    from firebase_admin import firestore

    return firestore.client(app=_firebase_app())
