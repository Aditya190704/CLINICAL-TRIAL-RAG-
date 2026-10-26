
import re
from typing import Any

from app.schemas import CriterionResult, JudgeOutput, PatientProfile


# ---------------------------------------------------------------------------
# Text Normalization
# ---------------------------------------------------------------------------

def _norm(value: str) -> str:
    """Normalize text for case-insensitive evidence verification."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _quote_in(text_norm: str, quote: str) -> bool:
    """Verify meaningful parts of a quote, including ellipsis-separated text."""
    parts = [
        part.strip()
        for part in re.split(r"\.\.\.|…", quote or "")
        if len(_norm(part)) >= 12
    ]
    return bool(parts) and all(_norm(part) in text_norm for part in parts)


def _collect_profile_values(value: Any) -> list[str]:
    """Collect scalar values from a validated structured patient profile."""
    collected: list[str] = []

    if isinstance(value, str):
        if value.strip():
            collected.append(value.strip())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        collected.append(str(value))
    elif isinstance(value, dict):
        for nested_value in value.values():
            collected.extend(_collect_profile_values(nested_value))
    elif isinstance(value, (list, tuple, set)):
        for nested_value in value:
            collected.extend(_collect_profile_values(nested_value))

    return collected


def _patient_evidence_verified(
    evidence: str,
    case: str,
    profile: PatientProfile,
) -> bool:
    """
    Accept evidence found in the original case or represented in the validated
    profile. This is a lexical check, not a semantic entailment check.
    """
    evidence_norm = _norm(evidence)
    if not evidence_norm:
        return False

    case_norm = _norm(case)
    if evidence_norm in case_norm:
        return True

    profile_values = _collect_profile_values(
        profile.model_dump(mode="json")
    )

    # First try exact normalized matching against individual profile values.
    if any(
        evidence_norm in _norm(value)
        for value in profile_values
        if _norm(value)
    ):
        return True

    # Permit simple age paraphrases when the evidence explicitly includes
    # the known numeric age. This does not verify other paraphrases.
    age = profile.age_years
    if age is not None:
        age_text = f"{age:g}"
        age_pattern = rf"(?<!\d){re.escape(age_text)}(?!\d)"
        if re.search(age_pattern, evidence_norm):
            return True

    return False


def _metastatic_status_is_explicit(criterion_quote: str, evidence: str) -> bool:
    """Node status and absent reporting do not establish distant metastasis."""
    metastatic_criterion = re.search(
        r"\bmetasta(?:sis|ses|tic)\b|\bdistant disease\b",
        criterion_quote,
        re.I,
    )
    explicit_status = re.search(
        r"\bmetasta(?:sis|ses|tic)\b|\bdistant disease\b|\bM[01](?:[a-c])?\b",
        evidence,
        re.I,
    )
    return not metastatic_criterion or bool(explicit_status)


# ---------------------------------------------------------------------------
# Deterministic Age / Sex Checks
# ---------------------------------------------------------------------------

def _age_check(
    profile: PatientProfile,
    trial: dict[str, Any],
) -> list[CriterionResult]:
    """Apply deterministic checks using structured trial metadata."""
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
                    criterion_quote=(
                        "Minimum age: " + str(trial.get("min_age", lo))
                    ),
                    patient_evidence=f"Age: {age:g}",
                    impact="BLOCKS",
                    explanation=(
                        "The patient's age is below the trial's minimum "
                        "age requirement."
                    ),
                )
            )
        elif hi is not None and age > hi:
            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote=(
                        "Maximum age: " + str(trial.get("max_age", hi))
                    ),
                    patient_evidence=f"Age: {age:g}",
                    impact="BLOCKS",
                    explanation=(
                        "The patient's age is above the trial's maximum "
                        "age requirement."
                    ),
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
                    explanation=(
                        "The patient's age is within the structured trial "
                        "age range."
                    ),
                )
            )

    sex = str(trial.get("sex", "ALL")).upper()
    patient_sex = str(profile.sex or "UNKNOWN").upper()

    if sex not in {"ALL", "UNKNOWN", ""} and patient_sex != "UNKNOWN":
        matches = sex == patient_sex
        results.append(
            CriterionResult(
                source="STRUCTURED",
                criterion_type="INCLUSION",
                criterion_quote=f"Sex: {sex}",
                patient_evidence=f"Sex: {patient_sex}",
                impact="SUPPORTS" if matches else "BLOCKS",
                explanation=(
                    "The patient's sex matches the trial requirement."
                    if matches
                    else "The patient's sex does not match the trial requirement."
                ),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Verify Model Assessment
# ---------------------------------------------------------------------------

def verify_judge_output(
    case: str,
    profile: PatientProfile,
    trial: dict[str, Any],
    output: JudgeOutput,
) -> tuple[list[CriterionResult], str, int]:
    """
    Verify trial quotations and patient evidence before accepting criterion
    assessments. Unsupported patient evidence becomes UNKNOWN.
    """
    eligibility_text = str(trial.get("eligibility_text") or "")
    eligibility_norm = _norm(eligibility_text)

    verified: list[CriterionResult] = []
    dropped = 0

    for item in output.criteria:
        quote = (item.criterion_quote or "").strip()
        patient_evidence = (
            item.patient_evidence_quote or ""
        ).strip() 

        # Never accept a criterion quotation that cannot be found in the
        # supplied trial eligibility text.
        if not quote or _norm(quote) not in eligibility_norm:
            dropped += 1
            continue

        impact = item.impact

        if impact == "UNKNOWN":
            patient_evidence = ""
        elif not _patient_evidence_verified(
            patient_evidence,
            case,
            profile,
        ) or not _metastatic_status_is_explicit(quote, patient_evidence):
            impact = "UNKNOWN"
            patient_evidence = ""

        verified.append(
            CriterionResult(
                source="TRIAL_TEXT",
                criterion_type=item.criterion_type,
                criterion_quote=quote,
                patient_evidence=patient_evidence or None,
                impact=impact,
                explanation=(item.explanation or "").strip()[:1000],
            )
        )

    # Structured age/sex checks remain independent of model assessments.
    results = _age_check(profile, trial) + verified

    if not verified and not results:
        results.append(
            CriterionResult(
                source="STRUCTURED",
                criterion_type="INCLUSION",
                criterion_quote="Eligibility assessment could not be completed",
                patient_evidence=None,
                impact="UNKNOWN",
                explanation=(
                    "No trial criterion could be verified for assessment. "
                    "Manual review is required."
                ),
            )
        )

    summary = (
        (output.summary or "").strip()[:2000]
        or "Insufficient evidence was provided to assess the trial criteria."
    )

    return results, summary, dropped


# ---------------------------------------------------------------------------
# Deterministic Final Verdict
# ---------------------------------------------------------------------------

def compute_verdict(criteria: list[CriterionResult]) -> str:
    """
    The LLM never determines the final eligibility label.

    Rules:
    - Any BLOCKS criterion -> EXCLUDED
    - No SUPPORTS criterion and no blocker -> COULD_NOT_ASSESS
    - Otherwise -> POSSIBLY_ELIGIBLE

    These are preliminary research-screening labels, not confirmed eligibility.
    """
    if any(item.impact == "BLOCKS" for item in criteria):
        return "EXCLUDED"

    if not any(item.impact == "SUPPORTS" for item in criteria):
        return "COULD_NOT_ASSESS"

    return "POSSIBLY_ELIGIBLE"
