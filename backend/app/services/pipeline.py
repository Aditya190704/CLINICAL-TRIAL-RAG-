
"""API-facing entry point for clinical-trial matching."""

from __future__ import annotations

import logging
import re
import time

from app.agents.workflow import run_adk_workflow
from app.schemas import MatchResponse

logger = logging.getLogger(__name__)

MIN_CASE_LENGTH = 40
MAX_CASE_LENGTH = 8000

# Basic screening for common direct identifiers.
# This is a guardrail, not a complete de-identification system.
PHI_PATTERNS = {
    "email": re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        re.IGNORECASE,
    ),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(
        r"(?<!\d)(?:\+?1[\s.-]?)?"
        r"(?:\(\d{3}\)|\d{3})[\s.-]?"
        r"\d{3}[\s.-]?\d{4}(?!\d)"
    ),
}

# Single regex pattern for backward-compatibility with tests/callers
PHI = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b\d{3}-\d{2}-\d{4}\b|(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)",
    re.IGNORECASE,
)

ORDER = {"ELIGIBLE": 0, "POSSIBLY_ELIGIBLE": 1, "EXCLUDED": 2}


def _validate_case(case: str) -> str:
    """Validate the case without logging its contents."""
    if not isinstance(case, str):
        raise ValueError("Patient case must be provided as text.")

    case = case.strip()

    if len(case) < MIN_CASE_LENGTH:
        raise ValueError(
            f"Patient case must contain at least {MIN_CASE_LENGTH} characters."
        )

    if len(case) > MAX_CASE_LENGTH:
        raise ValueError(
            f"Patient case must not exceed {MAX_CASE_LENGTH} characters."
        )

    return case


def _contains_possible_direct_identifier(case: str) -> bool:
    """Return True when a common direct identifier pattern is detected."""
    return any(pattern.search(case) for pattern in PHI_PATTERNS.values())


def run(case: str) -> MatchResponse:
    """Validate an anonymous patient case and execute the matching workflow."""
    case = _validate_case(case)

    if _contains_possible_direct_identifier(case):
        raise ValueError(
            "The patient case may contain a direct personal identifier, "
            "such as an email address, phone number, or SSN. Remove direct "
            "identifiers and submit an anonymized clinical summary."
        )

    started_at = time.perf_counter()

    try:
        response = run_adk_workflow(case)

        if not isinstance(response, MatchResponse):
            response = MatchResponse.model_validate(response)

        elapsed_seconds = round(time.perf_counter() - started_at, 3)

        logger.info(
            "Clinical-trial matching completed in %.3f seconds.",
            elapsed_seconds,
        )

        return response.model_copy(
            update={"latency_seconds": elapsed_seconds}
        )

    except ValueError:
        # Preserve input and validation errors for the API layer.
        raise

    except Exception as exc:
        # Log the traceback, but never log the patient case or medical text.
        logger.exception(
            "Clinical-trial matching workflow failed (%s).",
            type(exc).__name__,
        )

        raise RuntimeError(
            "Clinical-trial matching failed. Check the backend logs for details."
        ) from exc
