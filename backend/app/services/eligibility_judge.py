import re
from typing import Any

from app.schemas import CriterionResult, JudgeOutput, PatientProfile

# ---------------------------------------------------------------------------
# Text Normalization
# ---------------------------------------------------------------------------

def _norm(value: str) -> str:
    """Normalize text for case-insensitive substring verification."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _quote_in(text_norm: str, quote: str) -> bool:
    """Check quote text; support ellipses only when each meaningful part exists."""
    parts = [
        part.strip()
        for part in re.split(r"\.\.\.|…", quote or "")
        if len(_norm(part)) >= 12
    ]
    return bool(parts) and all(_norm(part) in text_norm for part in parts)


# ---------------------------------------------------------------------------
# Deterministic Age / Sex Checks
# ---------------------------------------------------------------------------

def _age_check(profile: PatientProfile, trial: dict) -> list[CriterionResult]:
    """Apply deterministic checks from structured trial metadata."""
    results: list[CriterionResult] = []
    age = profile.age_years

    if age is not None:
        lo = trial.get("min_age_years")
        hi = trial.get("max_age_years")

        if lo is not None and age < lo:
            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote="Minimum age: " + str(trial.get("min_age", lo)),
                    patient_evidence=f"Age: {age:g}",
                    impact="BLOCKS",
                    explanation="The patient's age is below the trial's minimum age requirement.",
                )
            )
        elif hi is not None and age > hi:
            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote="Maximum age: " + str(trial.get("max_age", hi)),
                    patient_evidence=f"Age: {age:g}",
                    impact="BLOCKS",
                    explanation="The patient's age is above the trial's maximum age requirement.",
                )
            )
        elif lo is not None or hi is not None:
            age_range = (
                f"Age range: {trial.get('min_age') or 'N/A'} "
                f"to {trial.get('max_age') or 'N/A'}"
            )
            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote=age_range,
                    patient_evidence=f"Age: {age:g}",
                    impact="SUPPORTS",
                    explanation="The patient's age is within the structured trial age range.",
                )
            )

    sex = trial.get("sex", "ALL")
    if sex != "ALL" and profile.sex != "UNKNOWN":
        matches = sex == profile.sex
        results.append(
            CriterionResult(
                source="STRUCTURED",
                criterion_type="INCLUSION",
                criterion_quote=f"Sex: {sex}",
                patient_evidence=f"Sex: {profile.sex}",
                impact="SUPPORTS" if matches else "BLOCKS",
                explanation=(
                    "The patient's sex matches the trial requirement."
                    if matches
                    else "The patient's sex does not match the trial requirement."
                ),
            )
        )

    return results


def verify_judge_output(
    case: str,
    profile: PatientProfile,
    trial: dict[str, Any],
    output: JudgeOutput,
) -> tuple[list[CriterionResult], str, int]:
    """Verify model quotes and convert unknown or unsupported evidence safely."""
    eligibility_text = str(trial.get("eligibility_text") or "")
    eligibility_norm = _norm(eligibility_text)
    case_norm = _norm(case)
    verified: list[CriterionResult] = []
    dropped = 0

    for item in output.criteria:
        quote = item.criterion_quote.strip()
        patient_evidence = item.patient_evidence_quote.strip()
        if not quote or _norm(quote) not in eligibility_norm:
            dropped += 1
            continue

        impact = item.impact
        if impact == "UNKNOWN":
            patient_evidence = ""
        elif not patient_evidence or _norm(patient_evidence) not in case_norm:
            impact = "UNKNOWN"
            patient_evidence = ""

        verified.append(CriterionResult(
            source="TRIAL_TEXT",
            criterion_type=item.criterion_type,
            criterion_quote=quote,
            patient_evidence=patient_evidence or None,
            impact=impact,
            explanation=item.explanation.strip()[:1000],
        ))

    results = _age_check(profile, trial) + verified
    if not verified:
        results.append(CriterionResult(
            source="STRUCTURED",
            criterion_type="INCLUSION",
            criterion_quote="Eligibility assessment could not be completed",
            patient_evidence=None,
            impact="UNKNOWN",
            explanation="No trial criterion could be verified for assessment. Manual review is required.",
        ))

    return (
        results,
        output.summary.strip()[:2000] or "Insufficient evidence was provided to assess the trial criteria.",
        dropped,
    )


# ---------------------------------------------------------------------------
# Deterministic Final Verdict
# ---------------------------------------------------------------------------

def compute_verdict(criteria: list[CriterionResult]) -> str:
    """
    The LLM NEVER determines the final eligibility label.

    Rules:
    - Any BLOCKS criterion -> EXCLUDED
    - Otherwise, any UNKNOWN criterion or no criteria -> POSSIBLY_ELIGIBLE
    - Otherwise -> POSSIBLY_ELIGIBLE

    Assessments are selective and may omit unreported or unassessed criteria,
    so passing the assessed criteria alone cannot establish trial eligibility.
    """
    if any(c.impact == "BLOCKS" for c in criteria):
        return "EXCLUDED"

    if any(c.impact == "UNKNOWN" for c in criteria) or not criteria:
        return "POSSIBLY_ELIGIBLE"

    return "POSSIBLY_ELIGIBLE"
