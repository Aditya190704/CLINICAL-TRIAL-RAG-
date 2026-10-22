"""Deterministic emergency and patient-fact safety checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.schemas import PatientProfile
from app.services.patient_parser import _validate_profile
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
    age_values = list(dict.fromkeys(item.group(1) for item in ages))
    if len(age_values) > 1:
        conflicts.append("Conflicting ages are stated in the case.")
        excluded.extend(age_values)

    stages = list(re.finditer(r"\b(?:stage|stg\.?\s*)\s*(IV|III|II|I|4|3|2|1|0)([A-D]?)\b", case, re.I))
    stage_values = list(dict.fromkeys((item.group(1) + item.group(2)).upper() for item in stages))
    if len(stage_values) > 1:
        conflicts.append("Conflicting disease stages are stated in the case.")
        excluded.extend(stage_values)

    return conflicts, excluded


def validate_extracted_profile(profile: PatientProfile, case: str) -> PatientProfile:
    """Validate extracted facts and remove values involved in detected conflicts."""
    validated = _validate_profile(profile, case)
    conflicts, excluded = detect_supported_conflicts(case)
    if excluded:
        excluded_norm = {value.casefold() for value in excluded}
        validated.key_findings = [
            fact for fact in validated.key_findings
            if not any(value in fact.casefold() for value in excluded_norm)
        ]
        if any(conflict.startswith("Conflicting ages") for conflict in conflicts):
            validated.age_years = None
    return validated


def safe_search_query(query: str, case: str, profile: PatientProfile) -> str:
    """Accept only text grounded in the sanitized case; preserve stable wording."""
    clean_case = " ".join(remove_instruction_like_clauses(case).split())
    query = " ".join(remove_instruction_like_clauses(str(query or "")).split())[:2000]
    source_terms = set(re.findall(r"[a-z0-9]+", clean_case.casefold()))
    terms = re.findall(r"[a-z0-9]+", query.casefold())
    if not terms or any(term not in source_terms for term in terms):
        raise ValueError("Search query contains unsupported facts.")
    return query

