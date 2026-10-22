
"""Extract an explicit, structured patient profile using Gemini on Vertex AI.

The parser extracts facts for retrieval and eligibility assessment. It does not
diagnose the patient or infer missing clinical information.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.config import settings
from app.schemas import PatientProfile

logger = logging.getLogger(__name__)

MAX_CASE_LENGTH = 8000
MAX_SEARCH_QUERY_LENGTH = 2000


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _fact_is_supported(fact: str, case_normalized: str) -> bool:
    normalized_fact = _normalized_text(fact)
    return bool(normalized_fact) and normalized_fact in case_normalized


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
    case_normalized = _normalized_text(patient_case)

    # Age must be explicitly supported by the submitted case.
    if profile.age_years is not None:
        age_text = str(profile.age_years).rstrip("0").rstrip(".")
        age_is_present = bool(
            re.search(
                rf"\b{re.escape(age_text)}[\s-]*(?:years?\s*old|year-old|yo)\b"
                rf"|\b(?:age|aged)\s*{re.escape(age_text)}\b",
                patient_case,
                flags=re.IGNORECASE,
            )
        )

        if not age_is_present:
            profile.age_years = None

    stated_sexes = {
        value.upper()
        for value in re.findall(r"\b(?:male|female)\b", patient_case, re.IGNORECASE)
    }
    if profile.sex not in stated_sexes or len(stated_sexes) != 1:
        profile.sex = "UNKNOWN"

    for field_name in (
        "primary_conditions",
        "comorbidities",
        "current_medications",
        "prior_treatments",
        "key_findings",
    ):
        facts = getattr(profile, field_name)
        setattr(
            profile,
            field_name,
            [
                fact
                for fact in facts
                if _fact_is_supported(fact, case_normalized)
            ],
        )

    # Keep generated search terms only when their words occur in the case.
    case_words = set(re.findall(r"[a-z0-9]+", case_normalized))
    search_words = re.findall(
        r"[a-z0-9]+",
        (profile.search_query or "").casefold(),
    )
    search_query = " ".join(word for word in search_words if word in case_words)
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
            http_options=types.HttpOptions(
                timeout=max(1, round(settings.adk_timeout_seconds * 1000))
            ),
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
