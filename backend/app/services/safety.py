"""Deterministic emergency and patient-fact safety checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.schemas import PatientProfile
from app.services.patient_parser import _explicit_search_facts, _validate_profile
from app.services.untrusted_text import remove_instruction_like_clauses

EMERGENCY_NOTICE = (
    "This description may indicate a medical emergency. Seek emergency care now, "
    "or contact local emergency services."
)
URGENT_SIGN_FILE = Path(__file__).resolve().parents[1] / "urgent_signs.json"

KEY_FACTS = {
    "diagnosis": "Main diagnosis or condition",
    "age": "Age",
    "prior_treatments": "Prior treatments",
    "key_findings": "Disease stage, biomarkers, or performance status",
}


def _config() -> dict[str, list[str]]:
    data = json.loads(URGENT_SIGN_FILE.read_text(encoding="utf-8"))
    signs = data["warning_signs"]
    negations = data["negation_terms"]
    if not isinstance(signs, list) or not signs or not isinstance(negations, list):
        raise ValueError("Urgent-sign configuration is invalid.")
    if any(not isinstance(item, str) or not item.strip() for item in signs + negations):
        raise ValueError("Urgent-sign configuration contains an invalid item.")
    return {"warning_signs": signs, "negation_terms": negations}


def screen_urgent_case(case: str) -> bool:
    """Return true for configured warning phrases not preceded by simple negation."""
    config = _config()
    for sign in config["warning_signs"]:
        for match in re.finditer(rf"(?<!\w){re.escape(sign)}(?!\w)", case, re.I):
            preceding = case[max(0, match.start() - 100):match.start()].casefold()
            clauses = re.split(r"[.;:,!?]|\b(?:but|however|although|yet|and)\b", preceding)
            clause = clauses[-1] if clauses else preceding
            words = re.findall(r"[a-z]+", clause)[-5:]
            window = " ".join(words)
            if any(
                re.search(rf"(?:^|\s){re.escape(term.casefold())}(?:$|\s)", window)
                for term in config["negation_terms"]
            ):
                continue
            if re.search(r"\bno\s+history\s+of\s*$", preceding):
                continue
            return True
    return False


def derive_missing_facts(profile: PatientProfile) -> list[str]:
    missing: list[str] = []
    if not profile.primary_conditions:
        missing.append(KEY_FACTS["diagnosis"])
    if profile.age_years is None:
        missing.append(KEY_FACTS["age"])
    if not profile.prior_treatments:
        missing.append(KEY_FACTS["prior_treatments"])
    if not profile.key_findings:
        missing.append(KEY_FACTS["key_findings"])
    return missing


def detect_supported_conflicts(case: str) -> tuple[list[str], list[str]]:
    """Detect simple conflicting ages/stages and return the values to exclude."""
    conflicts: list[str] = []
    excluded: list[str] = []

    ages = list(re.finditer(r"\b(\d{1,3})(?:\s*years?\s*old|-year-old|\s*yo)\b", case, re.I))
    ages.extend(re.finditer(r"\b(?:age|aged)\s+(\d{1,3})\b", case, re.I))
    age_values = list(dict.fromkeys(item.group(1) for item in ages))
    if len(age_values) > 1:
        conflicts.append("Conflicting ages are stated in the case.")
        excluded.extend(age_values)

    stages = list(re.finditer(r"\b(?:stage|stg\.?\s*)\s*(IV|III|II|I|4|3|2|1|0)([A-D]?)\b", case, re.I))
    stage_values = list(dict.fromkeys((item.group(1) + item.group(2)).upper() for item in stages))
    if len(stage_values) > 1:
        conflicts.append("Conflicting disease stages are stated in the case.")
        excluded.extend(stage_values)

    clinical_t_stages = list(dict.fromkeys(
        item.group(0).upper()
        for item in re.finditer(r"\bcT[0-4](?:[a-c])?\b", case, re.I)
    ))
    if len(clinical_t_stages) > 1:
        conflicts.append("Conflicting clinical T stages are stated in the case.")
        excluded.extend(clinical_t_stages)

    return conflicts, excluded


def remove_conflicting_fact_mentions(case: str, excluded_values: list[str]) -> str:
    """Remove age and stage statements whose values conflict in the case."""
    safe_case = case
    for value in excluded_values:
        escaped = re.escape(str(value))
        if re.fullmatch(r"cT[0-4](?:[a-c])?", value, re.I):
            pattern = rf"\b{escaped}\b"
        elif value.isdigit():
            pattern = rf"\b(?:(?:age|aged)\s*)?{escaped}(?:\s*years?\s*old|-year-old|\s*yo)?\b"
        else:
            pattern = rf"\b(?:stage\s*|stg\.?\s*){escaped}[A-D]?\b"
        safe_case = re.sub(pattern, " [conflicting fact omitted] ", safe_case, flags=re.I)
    return " ".join(safe_case.split())


def validate_extracted_profile(profile: PatientProfile, case: str) -> PatientProfile:
    """Validate extracted facts and remove values involved in detected conflicts."""
    raw_primary_conditions = list(profile.primary_conditions)
    raw_key_findings = list(profile.key_findings)
    validated = _validate_profile(profile, case)
    conflicts, excluded = detect_supported_conflicts(case)
    stage_values = {
        value.casefold()
        for value in excluded
        if re.fullmatch(r"(?:IV|III|II|I|4|3|2|1|0)[A-D]?|cT[0-4](?:[a-c])?", value, re.I)
    }
    if stage_values:
        def remove_conflicting_stage(fact: str) -> str:
            for value in stage_values:
                if re.fullmatch(r"cT[0-4](?:[a-c])?", value, re.I):
                    pattern = rf"\b{re.escape(value)}\b"
                else:
                    pattern = rf"\b(?:stage\s*|stg\.?\s*){re.escape(value)}\b"
                fact = re.sub(pattern, " ", fact, flags=re.I)
            return " ".join(fact.split()).strip(" ,;:-")

        for field_name in ("primary_conditions", "key_findings"):
            cleaned_facts = [
                remove_conflicting_stage(fact)
                for fact in (
                    raw_primary_conditions
                    if field_name == "primary_conditions"
                    else raw_key_findings
                )
            ]
            case_normalized = re.sub(r"[^a-z0-9]+", " ", case.casefold()).strip()
            supported_facts = [
                fact for fact in cleaned_facts
                if fact
                and re.sub(r"[^a-z0-9]+", " ", fact.casefold()).strip() in case_normalized
            ]
            existing = [
                remove_conflicting_stage(fact)
                for fact in getattr(validated, field_name)
            ]
            existing = [fact for fact in existing if fact]
            setattr(validated, field_name, list(dict.fromkeys([*existing, *supported_facts])))
    if any(conflict.startswith("Conflicting ages") for conflict in conflicts):
        validated.age_years = None

    safe_case = remove_instruction_like_clauses(
        remove_conflicting_fact_mentions(case, excluded)
    )
    validated.key_findings = list(dict.fromkeys([
        *validated.key_findings,
        *_explicit_search_facts(safe_case),
    ]))

    query_facts = list(dict.fromkeys([
        *validated.primary_conditions,
        *validated.key_findings,
        *validated.prior_treatments,
        *validated.current_medications,
    ]))
    validated.search_query = (
        " ".join(query_facts)
        or remove_instruction_like_clauses(
            remove_conflicting_fact_mentions(case, excluded)
        )
    )[:2000]
    return validated


def safe_search_query(query: str, case: str, profile: PatientProfile) -> str:
    """Accept only text grounded in the sanitized case; preserve stable wording."""
    clean_case = " ".join(remove_instruction_like_clauses(case).split())
    query = " ".join(remove_instruction_like_clauses(str(query or "")).split())[:2000]
    source_terms = set(re.findall(r"[a-z0-9]+", clean_case.casefold()))
    terms = re.findall(r"[a-z0-9]+", query.casefold())
    if terms and all(term in source_terms for term in terms):
        return query

    # Sanitization can remove an entire model-proposed query when it contains
    # an instruction-like clause. Fall back to already-validated profile facts.
    supported_facts = [
        *profile.primary_conditions,
        *profile.comorbidities,
        *profile.current_medications,
        *profile.prior_treatments,
        *profile.key_findings,
    ]
    fallback = " ".join(
        fact for fact in supported_facts
        if fact and re.search(
            rf"(?<![a-z0-9]){re.escape(fact.casefold())}(?![a-z0-9])",
            clean_case.casefold(),
        )
    )
    if fallback:
        return fallback[:2000]
    raise ValueError("Search query contains unsupported facts.")
