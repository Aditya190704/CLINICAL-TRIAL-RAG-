
"""Extract an explicit, structured patient profile using Gemini on Vertex AI.

The parser extracts facts for retrieval and eligibility assessment. It does not
diagnose the patient or infer missing clinical information.
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.config import settings
from app.schemas import PatientProfile

logger = logging.getLogger(__name__)

MAX_CASE_LENGTH = 8000
MAX_SEARCH_QUERY_LENGTH = 2000


def _build_prompt(patient_case: str) -> str:
    return f"""
You are a careful clinical information extraction assistant.

Extract a structured profile from the supplied patient case. The output will
be used to search clinical trials and compare the patient against eligibility
criteria.

PATIENT CASE:
{patient_case}

EXTRACTION RULES:
1. Extract only facts explicitly stated in the patient case.
2. Do not diagnose the patient or add facts from general medical knowledge.
3. If age is not explicitly stated, set age_years to null.
4. Set sex to MALE or FEMALE only when explicitly stated. Otherwise use UNKNOWN.
5. Include conditions, comorbidities, medications, prior treatments, and key
   findings only when supported by the case.
6. Do not assume that an unmentioned condition, medication, treatment, or
   risk factor is absent.
7. Do not interpret missing information as a negative finding.
8. Preserve clinically important details such as disease stage, biomarkers,
   treatment line, performance status, measurable disease, and organ function
   when explicitly stated.
9. Avoid adding patient names, addresses, phone numbers, email addresses, or
   other direct identifiers.
10. Create search_query using the most useful explicit clinical terms for
    finding relevant trials. Do not invent facts to make the query more specific.
11. Keep the search query concise and within {MAX_SEARCH_QUERY_LENGTH} characters.
12. Return only the requested structured profile.
""".strip()


def _validate_profile(
    profile: PatientProfile,
    patient_case: str,
) -> PatientProfile:
    """Apply deterministic checks to the extracted profile."""
    case_lower = patient_case.casefold()

    # Age must be explicitly supported by the submitted case.
    if profile.age_years is not None:
        age_text = str(profile.age_years).rstrip("0").rstrip(".")
        age_is_present = (
            f"{age_text} year" in case_lower
            or f"{age_text}-year" in case_lower
            or f"age {age_text}" in case_lower
            or f"aged {age_text}" in case_lower
        )

        if not age_is_present:
            profile.age_years = None

    # Do not allow an empty search query to silently continue.
    search_query = (profile.search_query or "").strip()
    if not search_query:
        search_query = " ".join(patient_case.split()[:80])

    profile.search_query = search_query[:MAX_SEARCH_QUERY_LENGTH]

    return profile


def _parse_structured_response(response: Any) -> PatientProfile:
    parsed = getattr(response, "parsed", None)

    if isinstance(parsed, PatientProfile):
        return parsed

    if isinstance(parsed, dict):
        return PatientProfile.model_validate(parsed)

    response_text = getattr(response, "text", None)
    if response_text:
        return PatientProfile.model_validate_json(response_text)

    raise RuntimeError("The model returned no structured patient profile.")


def parse_patient(patient_case: str) -> PatientProfile:
    """Extract a PatientProfile from an anonymized patient case.

    Args:
        patient_case: Free-text clinical summary supplied by the user.

    Returns:
        A validated PatientProfile.

    Raises:
        ValueError: If the case is empty or exceeds the configured limit.
        RuntimeError: If structured extraction fails.
    """
    if not isinstance(patient_case, str):
        raise ValueError("Patient case must be provided as text.")

    patient_case = patient_case.strip()

    if not patient_case:
        raise ValueError("Patient case cannot be empty.")

    if len(patient_case) > MAX_CASE_LENGTH:
        raise ValueError(
            f"Patient case must not exceed {MAX_CASE_LENGTH} characters."
        )

    client = None

    try:
        client = genai.Client(
            vertexai=True,
            project=settings.gcp_project,
            location=settings.gcp_location,
        )

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=_build_prompt(patient_case),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PatientProfile,
                temperature=0,
            ),
        )

        profile = _parse_structured_response(response)
        return _validate_profile(profile, patient_case)

    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Patient profile extraction returned invalid structured data (%s).",
            type(exc).__name__,
        )
        raise RuntimeError(
            "The patient profile could not be extracted reliably. "
            "Please review the case and try again."
        ) from exc

    except Exception as exc:
        logger.error(
            "Patient profile extraction failed (%s).",
            type(exc).__name__,
        )
        raise RuntimeError(
            "Patient profile extraction failed. Please try again later."
        ) from exc

    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("Could not close the patient parser client.")
