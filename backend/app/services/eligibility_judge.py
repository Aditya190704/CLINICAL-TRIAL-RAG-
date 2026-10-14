import json
import re
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.schemas import CriterionResult, JudgeOutput, PatientProfile


# ---------------------------------------------------------------------------
# Gemini Client
# ---------------------------------------------------------------------------

def create_judge_client():
    """Create a fresh Gemini client for one trial evaluation."""
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM = """
You are a strict clinical-trial eligibility auditor.

Your task is to compare ONE anonymised patient case against ONE clinical
trial's eligibility criteria.

You are NOT a doctor and must NOT provide medical advice. You are only
performing evidence-based eligibility matching using the exact information
provided in the input.

ABSOLUTE RULES

1. USE ONLY PROVIDED INFORMATION
Use ONLY:
- the trial eligibility criteria provided in the prompt
- the patient case provided in the prompt

Do NOT use outside medical knowledge, internet knowledge, assumptions,
typical clinical practice, information from the trial title, or information
from your own knowledge.

If required information is not explicitly present, mark the criterion UNKNOWN.
Never infer missing information.

2. TRIAL CRITERIA MUST BE VERBATIM
For every assessed criterion, criterion_quote must be copied verbatim and
contiguously from the provided trial eligibility criteria.
Do not paraphrase, summarize, rewrite, combine separate sentences/bullets,
modify wording, correct grammar, or invent text.
Keep criterion_quote under 40 words whenever possible.
If you cannot copy a criterion exactly from the provided trial text, do not
include that criterion.

3. PATIENT EVIDENCE MUST BE VERBATIM
patient_evidence_quote must be copied verbatim from the patient case.
Do not paraphrase, summarize, infer, or modify wording.
If the patient case contains no relevant evidence, use an empty string and
set impact to UNKNOWN.

4. IMPACT DEFINITIONS
For an INCLUSION criterion:
- SUPPORTS: explicit evidence shows the patient satisfies it.
- BLOCKS: explicit evidence shows the patient fails it.
- UNKNOWN: the case does not provide enough information.

For an EXCLUSION criterion:
- SUPPORTS: explicit evidence shows the patient does NOT meet the exclusion.
- BLOCKS: explicit evidence shows the patient DOES meet the exclusion.
- UNKNOWN: the case does not provide enough information.

Absence of information is ALWAYS UNKNOWN. Never treat missing information
as evidence that the patient qualifies.

5. DO NOT DECIDE FINAL ELIGIBILITY
You are NOT responsible for producing the final eligibility label.
Only produce criterion-level assessments. The application calculates the
final verdict deterministically.

6. ASSESS RELEVANT CRITERIA
Assess at most 30 criteria. Prioritize:
1) criteria directly related to information explicitly present in the case;
2) criteria that could clearly block eligibility;
3) important criteria with missing information, which must be UNKNOWN.
Do not fill the output with irrelevant criteria.

7. INCLUSION AND EXCLUSION
Correctly identify each criterion as INCLUSION or EXCLUSION. Do not change
the meaning of the original criterion.

8. EXPLANATION
Keep explanations short and evidence-based. Do not introduce information
that is not explicitly present in the trial criterion or patient case.

9. SUMMARY
Return a concise 2-3 sentence summary describing only what the assessed
criteria demonstrate. Do not claim eligibility if important criteria remain
UNKNOWN. Do not introduce information not contained in the input.

10. EMPTY OR UNCERTAIN OUTPUT
If there is insufficient evidence to assess criteria, return:
{
  "criteria": [],
  "summary": "Insufficient evidence was provided to assess the trial criteria."
}
Never fabricate criteria or evidence.

11. OUTPUT FORMAT
Return only the structured response matching the provided schema.
Do not return Markdown, text outside the schema, or extra fields.
"""


# ---------------------------------------------------------------------------
# Text Normalization and Response Parsing
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


def _parse_judge_output(resp: Any) -> JudgeOutput | None:
    """
    Parse Gemini's structured response robustly.

    Gemini may return valid JSON in resp.text while resp.parsed is None.
    Try the parsed object first, then Pydantic JSON parsing, then json.loads.
    """
    parsed = getattr(resp, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, JudgeOutput):
            return parsed
        try:
            if hasattr(JudgeOutput, "model_validate"):
                return JudgeOutput.model_validate(parsed)
            return JudgeOutput.parse_obj(parsed)
        except Exception as exc:
            print(f"[WARN] Could not validate resp.parsed: {exc}")

    raw_text = getattr(resp, "text", None)
    if not raw_text or not raw_text.strip():
        print("[WARN] Gemini response text was empty.")
        return None

    cleaned = raw_text.strip()
    # Be tolerant if the model unexpectedly wraps JSON in Markdown fences.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        if hasattr(JudgeOutput, "model_validate_json"):
            return JudgeOutput.model_validate_json(cleaned)
        return JudgeOutput.parse_raw(cleaned)
    except Exception as exc:
        print(f"[WARN] Pydantic JSON parsing failed: {exc}")

    try:
        payload = json.loads(cleaned)
        if hasattr(JudgeOutput, "model_validate"):
            return JudgeOutput.model_validate(payload)
        return JudgeOutput.parse_obj(payload)
    except Exception as exc:
        print(f"[WARN] JSON parsing/validation failed: {exc}")
        print(f"[WARN] Raw Gemini response (first 2000 chars): {cleaned[:2000]}")
        return None


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


# ---------------------------------------------------------------------------
# Gemini Eligibility Judge
# ---------------------------------------------------------------------------

def judge(
    case: str,
    profile: PatientProfile,
    trial: dict,
) -> tuple[list[CriterionResult], str, int]:
    """Assess trial criteria, verify source quotes, and return verified results."""
    nct_id = trial.get("nct_id", "UNKNOWN")
    eligibility_text = trial.get("eligibility_text", "") or ""
    title = trial.get("title", "") or ""

    prompt = (
        f"TRIAL IDENTIFIER:\n{nct_id}\n\n"
        f"TRIAL TITLE:\n{title}\n\n"
        f"ELIGIBILITY CRITERIA (VERBATIM SOURCE TEXT):\n"
        f"{eligibility_text}\n\n"
        f"PATIENT CASE (VERBATIM SOURCE TEXT):\n{case}"
    )

    client = None
    try:
        # A separate client per evaluation avoids sharing a client that may
        # have been closed by another parallel workflow task.
        client = create_judge_client()
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=JudgeOutput,
                temperature=0.0,
                max_output_tokens=8192,
            ),
        )
    except Exception as exc:
        print(f"[ERROR] Gemini request failed for {nct_id}: {exc}")
        return (
            [],
            "Eligibility assessment failed because the Gemini request could not "
            "be completed. Manual review is required.",
            0,
        )
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as close_exc:
                print(f"[WARN] Gemini client cleanup failed: {close_exc}")

    # Important: resp.parsed can be None even when resp.text contains valid JSON.
    out = _parse_judge_output(resp)
    if out is None:
        fallback = _age_check(profile, trial)
        return (
            fallback,
            "Eligibility could not be fully assessed because the model did not "
            "return a valid structured response. Manual review is required.",
            0,
        )

    elig_n = _norm(eligibility_text)
    case_n = _norm(case)
    verified: list[CriterionResult] = []
    dropped = 0

    for c in out.criteria:
        criterion_quote = (c.criterion_quote or "").strip()
        patient_evidence = (c.patient_evidence_quote or "").strip()

        # A criterion must have a real quote from the supplied trial criteria.
        if not criterion_quote:
            dropped += 1
            print(f"[WARN] Dropped criterion with empty trial quote for {nct_id}")
            continue

        if _norm(criterion_quote) not in elig_n:
            dropped += 1
            print(
                f"[WARN] Dropped hallucinated/altered criterion for {nct_id}: "
                f"{criterion_quote}"
            )
            continue

        impact = c.impact
        if impact not in {"SUPPORTS", "BLOCKS", "UNKNOWN"}:
            impact = "UNKNOWN"
            patient_evidence = ""

        # UNKNOWN must not carry a claim of patient evidence.
        if impact == "UNKNOWN":
            patient_evidence = ""
        else:
            # Patient evidence must be a verbatim substring of the patient case.
            if (
                not patient_evidence
                or _norm(patient_evidence) not in case_n
            ):
                print(
                    f"[WARN] Invalid patient evidence for criterion: "
                    f"{criterion_quote}"
                )
                impact = "UNKNOWN"
                patient_evidence = ""

        criterion_type = c.criterion_type
        if criterion_type not in {"INCLUSION", "EXCLUSION"}:
            dropped += 1
            print(
                f"[WARN] Dropped criterion with invalid criterion_type for "
                f"{nct_id}: {criterion_type}"
            )
            continue

        verified.append(
            CriterionResult(
                source="TRIAL_TEXT",
                criterion_type=criterion_type,
                criterion_quote=criterion_quote,
                patient_evidence=patient_evidence,
                impact=impact,
                explanation=(c.explanation or "").strip(),
            )
        )

    summary = (
        out.summary.strip()
        if out.summary
        else "The assessed trial criteria were compared against the provided patient case."
    )

    return _age_check(profile, trial) + verified, summary, dropped


# ---------------------------------------------------------------------------
# Deterministic Final Verdict
# ---------------------------------------------------------------------------

def compute_verdict(criteria: list[CriterionResult]) -> str:
    """
    The LLM NEVER determines the final eligibility label.

    Rules:
    - Any BLOCKS criterion -> EXCLUDED
    - Otherwise, any UNKNOWN criterion or no criteria -> POSSIBLY_ELIGIBLE
    - Otherwise -> ELIGIBLE
    """
    if any(c.impact == "BLOCKS" for c in criteria):
        return "EXCLUDED"

    if any(c.impact == "UNKNOWN" for c in criteria) or not criteria:
        return "POSSIBLY_ELIGIBLE"

    return "ELIGIBLE"
