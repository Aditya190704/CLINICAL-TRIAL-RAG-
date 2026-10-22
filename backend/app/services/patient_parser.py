"""Deterministic validation helpers for ADK-extracted patient facts."""

from __future__ import annotations

import re

from app.schemas import PatientProfile
from app.services.untrusted_text import contains_instruction_like_text, remove_instruction_like_clauses

MAX_SEARCH_QUERY_LENGTH = 2000


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _fact_is_supported(fact: str, case_normalized: str) -> bool:
    normalized_fact = _normalized_text(fact)
    return bool(normalized_fact) and normalized_fact in case_normalized


def _validate_profile(profile: PatientProfile, patient_case: str) -> PatientProfile:
    """Discard extracted facts and query terms not supported by the case."""
    case_normalized = _normalized_text(patient_case)

    age_matches = list(re.finditer(
        r"\b(?:(?:age|aged)\s*)?(\d{1,3})(?:\s*years?\s*old|-year-old|\s*yo)?\b",
        patient_case,
        re.I,
    ))
    explicit_ages = [
        match for match in age_matches
        if re.search(r"(?:years?\s*old|-year-old|\byo\b)", match.group(0), re.I)
        or re.match(r"(?:age|aged)\s*\d", match.group(0), re.I)
    ]
    age_values = list(dict.fromkeys(int(match.group(1)) for match in explicit_ages))
    # The case is the source of truth; never let a model hallucinated age
    # leak into the profile or the session sidebar.
    profile.age_years = float(age_values[0]) if len(age_values) == 1 else None

    stated_sexes = {
        value.upper()
        for value in re.findall(r"\b(?:male|female)\b", patient_case, re.I)
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
        setattr(
            profile,
            field_name,
            [
                fact for fact in getattr(profile, field_name)
                if _fact_is_supported(fact, case_normalized)
                and not contains_instruction_like_text(fact)
            ],
        )

    # A stable query derived from the sanitized case avoids model paraphrases
    # changing retrieval between otherwise identical runs.
    profile.search_query = remove_instruction_like_clauses(patient_case)[:MAX_SEARCH_QUERY_LENGTH]
    return profile
