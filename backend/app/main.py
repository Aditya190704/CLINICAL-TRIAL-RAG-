
"""FastAPI application for clinical-trial matching and evidence chat."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.schemas import (
    ChatRequest,
    ChatResponse,
    MatchRequest,
    MatchResponse,
)
from app.safe_logging import log_safe_error, reset_request_id, set_request_id
from app.agents.workflow import WorkflowError
from app.services.chat import chat_answer
from app.services import pipeline
from app.services.pipeline import run as run_matching_pipeline
from app.services.trial_store import trials


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
    allow_methods=["GET", "POST", "OPTIONS"],
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
):
    """Match an anonymized patient case against processed clinical trials."""

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    try:
        return await pipeline.run_async(req.patient_case, request_id=request_id)

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
        log_safe_error(logger, request_id=request_id, step="matching", error=exc)

        raise HTTPException(
            status_code=500,
            detail="Matching failed. Please try again later.",
        ) from exc


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
):
    """Answer a question using evidence from the selected trials."""

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    try:
        result = await chat_answer(
            question=req.question,
            trial_ids=req.trial_ids,
            patient_case=req.patient_case,
        )

        # Preserve the frontend's chat-session state.
        result["session_id"] = req.session_id

        return ChatResponse.model_validate(result)

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except PermissionError as exc:
        log_safe_error(logger, request_id=request_id, step="chat_permission", error=exc)

        raise HTTPException(
            status_code=503,
            detail=(
                "A required service is unavailable "
                "or access is not configured. "
                "Check BigQuery IAM permissions and service credentials."
            ),
        ) from exc

    except RuntimeError as exc:
        log_safe_error(logger, request_id=request_id, step="chat", error=exc)

        raise HTTPException(
            status_code=500,
            detail=(
                "The trial evidence service failed. "
                "Please try again later."
            ),
        ) from exc

    except Exception as exc:
        log_safe_error(logger, request_id=request_id, step="chat", error=exc)

        raise HTTPException(
            status_code=500,
            detail=(
                "The chat request failed. "
                "Please try again later."
            ),
        ) from exc

