
"""FastAPI application for clinical-trial matching and evidence chat."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    ChatRequest,
    ChatResponse,
    MatchRequest,
    MatchResponse,
    SessionCreateRequest,
    SessionRenameRequest,
    ProfileInitializeRequest,
)
from app.safe_logging import log_safe_error, reset_request_id, set_request_id
from app.agents.workflow import WorkflowError
from app.services.chat import chat_answer
from app.services import pipeline
from app.services.trial_store import trials
from app.services.auth_dependency import require_firebase_user
from app.services import user_data


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------

def _allowed_origins() -> list[str]:
    """Read allowed frontend origins from environment configuration."""

    configured = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )

    origins = [
        origin.strip().rstrip("/")
        for origin in configured.split(",")
        if origin.strip()
    ]

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(origins))


# ---------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Clinical Trial Matcher API starting.")

    yield

    logger.info("Clinical Trial Matcher API shutting down.")


app = FastAPI(
    title="Clinical Trial Matcher API",
    description=(
        "Search clinical trials and review evidence relevant to a patient case. "
        "Results are preliminary and require clinical review."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_logging_middleware(
    request: Request,
    call_next,
):
    """Attach a request ID and log timing without logging request bodies."""

    request_id = (
        request.headers.get("X-Request-ID", "").strip()
        or str(uuid4())
    )

    request.state.request_id = request_id
    context_token = set_request_id(request_id)

    started = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code

        response.headers["X-Request-ID"] = request_id

        return response

    except Exception as exc:
        log_safe_error(logger, request_id=request_id, step="request", error=exc)
        raise

    finally:
        elapsed_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        logger.info("request_id=%s step=request_finished status=%s duration_ms=%s", request_id, status_code, elapsed_ms)
        reset_request_id(context_token)


# ---------------------------------------------------------------------
# Request validation handler
# ---------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    """Return a consistent validation response without echoing input values."""

    errors = []

    for error in exc.errors():
        errors.append(
            {
                "field": ".".join(
                    str(part)
                    for part in error.get("loc", [])
                ),
                "message": error.get(
                    "msg",
                    "Invalid input.",
                ),
                "type": error.get(
                    "type",
                    "validation_error",
                ),
            }
        )

    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed.",
            "errors": errors,
            "request_id": getattr(
                request.state,
                "request_id",
                None,
            ),
        },
    )


# ---------------------------------------------------------------------
# System routes
# ---------------------------------------------------------------------

@app.get("/", tags=["system"])
def root():
    """Return basic API information."""

    return {
        "service": "Clinical Trial Matcher API",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/api/health", tags=["system"])
def health():
    """Liveness check: confirms that the API process is responding."""
    indexed_count = 0
    try:
        indexed_count = len(trials() or [])
    except Exception:
        pass
    return {"status": "ok", "trials_indexed": indexed_count}


@app.get("/api/ready", tags=["system"])
def readiness():
    """Readiness check: verify that processed trial metadata is available."""

    try:
        trial_records = trials()

        if not trial_records:
            raise RuntimeError(
                "No processed trial records are available."
            )

        return {
            "status": "ready",
            "trials_indexed": len(trial_records),
        }

    except Exception as exc:
        log_safe_error(logger, request_id=None, step="readiness", error=exc)

        raise HTTPException(
            status_code=503,
            detail=(
                "The service is not ready. "
                "Trial data is unavailable."
            ),
        ) from exc


# ---------------------------------------------------------------------
# Clinical-trial matching route
# ---------------------------------------------------------------------

@app.post(
    "/api/match",
    response_model=MatchResponse,
    tags=["matching"],
)
async def match(
    req: MatchRequest,
    request: Request,
    user: dict = Depends(require_firebase_user),
):
    """Match an anonymized patient case against processed clinical trials."""

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )
    search_started = False
    search_completed = False

    try:
        # Reject direct identifiers before storing the narrative in Firestore.
        search_query = pipeline.validate_case(req.patient_case)
        session_id = req.session_id
        if session_id:
            session = await run_in_threadpool(user_data.get_session, user["uid"], session_id)
            if session is None:
                raise HTTPException(status_code=403, detail="This matching session is not accessible.")
        else:
            session = await run_in_threadpool(user_data.create_session, user["uid"])
            session_id = session["id"]

        saved_query = await run_in_threadpool(
            user_data.save_search_query,
            user["uid"],
            session_id,
            search_query,
        )
        if not saved_query:
            raise HTTPException(status_code=403, detail="This matching session is not accessible.")
        search_started = True

        result = await pipeline.run_async(search_query, request_id=request_id)
        saved = await run_in_threadpool(
            user_data.save_match_result,
            user["uid"],
            session_id,
            result.model_dump(mode="json"),
        )
        if not saved:
            raise HTTPException(status_code=403, detail="This matching session is not accessible.")
        search_completed = True
        return result.model_copy(update={"session_id": session_id})

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except PermissionError as exc:
        log_safe_error(logger, request_id=request_id, step="matching_permission", error=exc)

        raise HTTPException(
            status_code=503,
            detail=(
                "A required service is unavailable "
                "or access is not configured. "
                "Check BigQuery IAM permissions and service credentials."
            ),
        ) from exc

    except WorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    except RuntimeError as exc:
        log_safe_error(logger, request_id=request_id, step="matching", error=exc)

        raise HTTPException(
            status_code=500,
            detail="Matching failed. Please try again later.",
        ) from exc

    except Exception as exc:
        log_safe_error(logger, request_id=request_id, step="matching_storage", error=exc)

        raise HTTPException(status_code=503, detail="Matching session storage is unavailable.") from exc

    finally:
        if search_started and not search_completed:
            try:
                await run_in_threadpool(user_data.mark_search_failed, user["uid"], session_id)
            except Exception as exc:
                log_safe_error(logger, request_id=request_id, step="session_failure_status", error=exc)


# ---------------------------------------------------------------------
# Evidence-based trial chat route
# ---------------------------------------------------------------------

@app.post(
    "/api/trials/chat",
    response_model=ChatResponse,
    tags=["chat"],
)
async def trial_chat(
    req: ChatRequest,
    request: Request,
    user: dict = Depends(require_firebase_user),
):
    """Answer a question using evidence from the selected trials."""

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    try:
        if not req.session_id:
            raise HTTPException(status_code=400, detail="A saved matching session is required for chat.")
        session = await run_in_threadpool(user_data.get_session, user["uid"], req.session_id)
        if session is None:
            raise HTTPException(status_code=403, detail="This matching session is not accessible.")
        owned_trial_ids = set(session.get("matchedTrialIds") or [])
        if not req.trial_ids or any(trial_id not in owned_trial_ids for trial_id in req.trial_ids):
            raise HTTPException(status_code=403, detail="One or more trials are outside this matching session.")
        message_id = req.message_id or uuid4().hex
        existing_turn = await run_in_threadpool(
            user_data.load_chat_turn, user["uid"], req.session_id, message_id
        )
        if existing_turn is not None:
            return ChatResponse.model_validate({
                "answer": existing_turn["answer"],
                "citations": existing_turn["citations"],
                "missing_info": None,
                "session_id": req.session_id,
            })
        result = await chat_answer(
            question=req.question,
            trial_ids=req.trial_ids,
        )
        result["session_id"] = req.session_id
        response = ChatResponse.model_validate(result)
        persisted = await run_in_threadpool(
            user_data.persist_chat_turn,
            user["uid"],
            req.session_id,
            message_id,
            req.question,
            response.answer,
            [citation.model_dump(mode="json") for citation in response.citations],
        )
        if not persisted:
            raise HTTPException(status_code=403, detail="This matching session is not accessible.")
        return response

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except PermissionError as exc:
        log_safe_error(logger, request_id=request_id, step="chat_permission", error=exc)
        raise HTTPException(status_code=503, detail="A required evidence service is unavailable or access is not configured.") from exc

    except RuntimeError as exc:
        log_safe_error(logger, request_id=request_id, step="chat", error=exc)
        raise HTTPException(status_code=500, detail="The trial evidence service failed. Please try again later.") from exc

    except Exception as exc:
        log_safe_error(logger, request_id=request_id, step="chat", error=exc)
        raise HTTPException(status_code=500, detail="The chat request failed. Please try again later.") from exc


def _profile_or_service_error(user: dict) -> dict:
    try:
        return user_data.get_or_create_profile(user["uid"], user["email"], user["display_name"])
    except Exception as exc:
        log_safe_error(logger, request_id=None, step="profile_store", error=exc)
        raise HTTPException(status_code=503, detail="User profile storage is unavailable.") from exc


@app.get("/api/auth/profile", tags=["authentication"])
async def auth_profile(user: dict = Depends(require_firebase_user)):
    """Return the authenticated user's server-managed profile."""
    return await run_in_threadpool(_profile_or_service_error, user)


@app.post("/api/auth/profile", tags=["authentication"])
async def initialize_auth_profile(
    payload: ProfileInitializeRequest,
    user: dict = Depends(require_firebase_user),
):
    """Initialize the authenticated user's profile after account creation."""
    try:
        return await run_in_threadpool(
            user_data.initialize_profile,
            user["uid"],
            user["email"],
            payload.display_name,
        )
    except Exception as exc:
        log_safe_error(logger, request_id=None, step="profile_initialize", error=exc)
        raise HTTPException(status_code=503, detail="User profile storage is unavailable.") from exc


@app.get("/api/sessions", tags=["sessions"])
async def get_sessions(user: dict = Depends(require_firebase_user)):
    """List the authenticated user's recent matching sessions."""
    try:
        return await run_in_threadpool(user_data.list_sessions, user["uid"])
    except Exception as exc:
        log_safe_error(logger, request_id=None, step="session_list", error=exc)
        raise HTTPException(status_code=503, detail="Session storage is unavailable.") from exc


@app.post("/api/sessions", tags=["sessions"])
async def post_session(
    payload: SessionCreateRequest,
    user: dict = Depends(require_firebase_user),
):
    """Create an empty matching session for the authenticated user."""
    try:
        return await run_in_threadpool(user_data.create_session, user["uid"], payload.title)
    except Exception as exc:
        log_safe_error(logger, request_id=None, step="session_create", error=exc)
        raise HTTPException(status_code=503, detail="Session storage is unavailable.") from exc


@app.get("/api/sessions/{session_id}", tags=["sessions"])
async def get_session(session_id: str, user: dict = Depends(require_firebase_user)):
    """Return a session only when it belongs to the authenticated user."""
    session = await run_in_threadpool(user_data.get_session, user["uid"], session_id)
    if session is None:
        raise HTTPException(status_code=403, detail="This matching session is not accessible.")
    return session


@app.patch("/api/sessions/{session_id}", tags=["sessions"])
async def patch_session(
    session_id: str,
    payload: SessionRenameRequest,
    user: dict = Depends(require_firebase_user),
):
    """Rename an owned session."""
    updated = await run_in_threadpool(user_data.update_session_title, user["uid"], session_id, payload.title)
    if not updated:
        raise HTTPException(status_code=403, detail="This matching session is not accessible.")
    return {"id": session_id, "title": payload.title}


@app.delete("/api/sessions/{session_id}/messages", tags=["sessions"])
async def delete_session_messages(session_id: str, user: dict = Depends(require_firebase_user)):
    """Clear chat history from an owned session."""
    deleted = await run_in_threadpool(user_data.clear_chat_messages, user["uid"], session_id)
    if not deleted:
        raise HTTPException(status_code=403, detail="This matching session is not accessible.")
    return {"status": "cleared"}


@app.delete("/api/sessions/{session_id}/result", tags=["sessions"])
async def delete_session_result(session_id: str, user: dict = Depends(require_firebase_user)):
    """Clear saved match results from an owned session."""
    cleared = await run_in_threadpool(user_data.clear_match_result, user["uid"], session_id)
    if not cleared:
        raise HTTPException(status_code=403, detail="This matching session is not accessible.")
    return {"status": "cleared"}


@app.delete("/api/sessions/{session_id}", tags=["sessions"])
async def delete_one_session(session_id: str, user: dict = Depends(require_firebase_user)):
    """Delete an owned session and its chat messages."""
    deleted = await run_in_threadpool(user_data.delete_session, user["uid"], session_id)
    if not deleted:
        raise HTTPException(status_code=403, detail="This matching session is not accessible.")
    return {"status": "deleted"}


@app.delete("/api/sessions", tags=["sessions"])
async def delete_all_sessions(user: dict = Depends(require_firebase_user)):
    """Delete all matching sessions for the authenticated user."""
    await run_in_threadpool(user_data.clear_sessions, user["uid"])
    return {"status": "cleared"}

