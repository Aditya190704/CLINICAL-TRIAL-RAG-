"""Validated API-facing boundary for the clinical-trial workflow."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from uuid import uuid4

from app.agents.workflow import DISCLAIMER, WorkflowError, run_workflow_async
from app.schemas import MatchResponse, PatientProfile
from app.safe_logging import log_safe_error, reset_request_id, set_request_id
from app.services.safety import EMERGENCY_NOTICE, screen_urgent_case

MIN_CASE_LENGTH = 40
MAX_CASE_LENGTH = 8000

PHI_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(
        r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
    ),
}
PHI = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b\d{3}-\d{2}-\d{4}\b|(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)",
    re.I,
)
ORDER = {"ELIGIBLE": 0, "POSSIBLY_ELIGIBLE": 1, "EXCLUDED": 2}


def _validate_case(case: str) -> str:
    if not isinstance(case, str):
        raise ValueError("Patient case must be provided as text.")
    case = case.strip()
    if len(case) < MIN_CASE_LENGTH:
        raise ValueError(f"Patient case must contain at least {MIN_CASE_LENGTH} characters.")
    if len(case) > MAX_CASE_LENGTH:
        raise ValueError(f"Patient case must not exceed {MAX_CASE_LENGTH} characters.")
    return case


def _contains_possible_direct_identifier(case: str) -> bool:
    return any(pattern.search(case) for pattern in PHI_PATTERNS.values())


async def run_async(case: str, request_id: str | None = None) -> MatchResponse:
    """Validate, apply deterministic safety screening, then call the workflow."""
    case = _validate_case(case)
    if _contains_possible_direct_identifier(case):
        raise ValueError(
            "The patient case may contain a direct personal identifier, such as an "
            "email address, phone number, or SSN. Remove direct identifiers and "
            "submit an anonymized clinical summary."
        )

    request_id = request_id or str(uuid4())
    token = set_request_id(request_id)
    started = time.perf_counter()
    try:
        try:
            urgent = screen_urgent_case(case)
        except Exception as exc:
            log_safe_error(logging.getLogger(__name__), request_id=request_id, step="urgent_screen", error=exc)
            raise WorkflowError(
                "URGENT_SCREEN_FAILED",
                "The safety screen could not be completed. Please try again later.",
            ) from exc

        if urgent:
            return MatchResponse(
                patient_profile=PatientProfile(search_query="Search not performed"),
                matches=[],
                disclaimer=DISCLAIMER,
                emergency_notice=EMERGENCY_NOTICE,
                latency_seconds=round(time.perf_counter() - started, 3),
            )

        response = await run_workflow_async(case, request_id=request_id)
        return response.model_copy(update={"latency_seconds": round(time.perf_counter() - started, 3)})
    except (ValueError, WorkflowError):
        raise
    except Exception as exc:
        log_safe_error(logging.getLogger(__name__), request_id=request_id, step="pipeline", error=exc)
        raise WorkflowError(
            "WORKFLOW_FAILED",
            "Clinical-trial matching failed. Please try again later.",
        ) from exc
    finally:
        reset_request_id(token)


def run(case: str, request_id: str | None = None) -> MatchResponse:
    """Synchronous adapter; never starts a nested event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_async(case, request_id=request_id))
    raise RuntimeError("An event loop is already running; await pipeline.run_async instead.")
