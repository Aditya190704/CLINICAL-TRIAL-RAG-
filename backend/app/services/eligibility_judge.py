import re
from google import genai
from google.genai import types

from app.config import settings
from app.schemas import CriterionResult, JudgeOutput, PatientProfile


# ---------------------------------------------------------------------------
# Gemini Client
# ---------------------------------------------------------------------------

_client = genai.Client(
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

You are NOT a doctor and you must NOT provide medical advice.
You are only performing evidence-based eligibility matching using the
exact information provided in the input.

========================
ABSOLUTE RULES
========================

1. USE ONLY PROVIDED INFORMATION

Use ONLY:
- the trial eligibility criteria provided in the prompt
- the patient case provided in the prompt

Do NOT use:
- outside medical knowledge
- internet knowledge
- assumptions
- typical clinical practice
- information from the trial title
- information from your own knowledge

If the required information is not explicitly present, mark the criterion
as UNKNOWN.

Never infer missing information.

Example:

Patient case:
"The patient has lung cancer."

Criterion:
"Patient must have EGFR exon 19 deletion."

Correct:
UNKNOWN

Incorrect:
SUPPORTS

--------------------------------

2. TRIAL CRITERIA MUST BE VERBATIM

For every criterion you assess:

criterion_quote MUST be copied VERBATIM and CONTIGUOUSLY from the
provided trial eligibility criteria.

Do NOT:
- paraphrase
- summarize
- rewrite
- combine multiple sentences
- combine multiple bullets
- modify wording
- correct grammar
- invent text

Keep criterion_quote under 40 words whenever possible.

If you cannot copy a criterion exactly from the provided trial text,
DO NOT include that criterion.

--------------------------------

3. PATIENT EVIDENCE MUST BE VERBATIM

patient_evidence_quote MUST be copied VERBATIM from the patient case.

Do NOT:
- paraphrase the patient
- summarize the patient
- infer information
- modify wording

If the patient case contains no relevant evidence:

patient_evidence_quote = ""

and:

impact = UNKNOWN

--------------------------------

4. IMPACT DEFINITIONS

For an INCLUSION criterion:

SUPPORTS:
The patient clearly satisfies the criterion based on explicit evidence.

BLOCKS:
The patient clearly fails the criterion based on explicit evidence.

UNKNOWN:
The patient case does not provide enough information.

For an EXCLUSION criterion:

SUPPORTS:
The patient clearly does NOT meet the exclusion condition, and this
is supported by explicit patient evidence.

BLOCKS:
The patient clearly meets the exclusion condition, and this is supported
by explicit patient evidence.

UNKNOWN:
The patient case does not provide enough information.

IMPORTANT:
Absence of information is ALWAYS UNKNOWN.

Never treat missing information as evidence that the patient qualifies.

--------------------------------

5. DO NOT DECIDE FINAL ELIGIBILITY

You are NOT responsible for producing the final eligibility label.

Your job is only to produce criterion-level assessments.

The application will calculate the final verdict deterministically.

--------------------------------

6. ASSESS RELEVANT CRITERIA

Assess at most 30 criteria.

Prioritize:

1. Criteria directly related to information explicitly present in the
   patient case.

2. Criteria that could clearly block eligibility.

3. Important criteria for which information is missing and therefore
   require UNKNOWN.

Do not fill the output with irrelevant criteria.

--------------------------------

7. INCLUSION AND EXCLUSION

Correctly identify whether each criterion is:

INCLUSION
or
EXCLUSION

Do not change the meaning of the original criterion.

--------------------------------

8. EXPLANATION

The explanation must be short and evidence-based.

Do not introduce any information that is not explicitly present in the
trial criterion or patient case.

Good example:

"The patient case explicitly states that the patient has metastatic NSCLC."

Bad example:

"Patients with metastatic NSCLC are generally eligible for this type
of study."

The second statement uses outside knowledge and is forbidden.

--------------------------------

9. SUMMARY

Return a concise 2-3 sentence summary.

The summary must describe ONLY what the assessed criteria demonstrate.

Do not claim that the patient is eligible if important criteria remain
UNKNOWN.

Do not introduce information not contained in the input.

--------------------------------

10. EMPTY OR UNCERTAIN OUTPUT

If there is insufficient evidence to assess criteria, return:

{
  "criteria": [],
  "summary": "Insufficient evidence was provided to assess the trial criteria."
}

Never fabricate criteria or evidence.

--------------------------------

11. OUTPUT FORMAT

Return ONLY the structured response matching the provided schema.

Do not return Markdown.

Do not return explanations outside the schema.

Do not add extra fields.
"""


# ---------------------------------------------------------------------------
# Normalization Helper
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """
    Normalize text for safe substring verification.

    This is ONLY used to verify that Gemini's quoted text actually exists
    inside the original trial/patient text.
    """
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ---------------------------------------------------------------------------
# Deterministic Age / Sex Checks
# ---------------------------------------------------------------------------

def _age_check(
    profile: PatientProfile,
    trial: dict
) -> list[CriterionResult]:

    results = []

    age = profile.age_years

    # -------------------------
    # Age
    # -------------------------

    if age is not None:

        lo = trial.get("min_age_years")
        hi = trial.get("max_age_years")

        if lo is not None and age < lo:

            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote=(
                        "Minimum age: "
                        + str(trial.get("min_age", lo))
                    ),
                    patient_evidence=f"Age: {age:g}",
                    impact="BLOCKS",
                    explanation=(
                        "The patient's age is below the trial's "
                        "minimum age requirement."
                    ),
                )
            )

        elif hi is not None and age > hi:

            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote=(
                        "Maximum age: "
                        + str(trial.get("max_age", hi))
                    ),
                    patient_evidence=f"Age: {age:g}",
                    impact="BLOCKS",
                    explanation=(
                        "The patient's age is above the trial's "
                        "maximum age requirement."
                    ),
                )
            )

        elif lo is not None or hi is not None:

            age_range = (
                f"Age range: "
                f"{trial.get('min_age') or 'N/A'} "
                f"to "
                f"{trial.get('max_age') or 'N/A'}"
            )

            results.append(
                CriterionResult(
                    source="STRUCTURED",
                    criterion_type="INCLUSION",
                    criterion_quote=age_range,
                    patient_evidence=f"Age: {age:g}",
                    impact="SUPPORTS",
                    explanation=(
                        "The patient's age is within the "
                        "structured trial age range."
                    ),
                )
            )

    # -------------------------
    # Sex
    # -------------------------

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
                    else
                    "The patient's sex does not match the trial requirement."
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
    trial: dict
) -> tuple[list[CriterionResult], str, int]:

    prompt = (
        f"TRIAL IDENTIFIER:\n"
        f"{trial['nct_id']}\n\n"

        f"TRIAL TITLE:\n"
        f"{trial['title']}\n\n"

        f"ELIGIBILITY CRITERIA (VERBATIM SOURCE TEXT):\n"
        f"{trial['eligibility_text']}\n\n"

        f"PATIENT CASE (VERBATIM SOURCE TEXT):\n"
        f"{case}"
    )

    # -----------------------------------------------------------------------
    # Gemini Request
    # -----------------------------------------------------------------------

    try:

        resp = _client.models.generate_content(
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

        print(
            f"[ERROR] Gemini request failed for "
            f"{trial.get('nct_id', 'UNKNOWN')}: {exc}"
        )

        fallback = _age_check(profile, trial)

        return (
            fallback,
            "Eligibility assessment failed because the Gemini request could not be completed.",
            0,
        )

    # -----------------------------------------------------------------------
    # Validate Gemini Structured Output
    # -----------------------------------------------------------------------

    out = resp.parsed

    if out is None:

        print(
            f"[WARN] Gemini returned no structured output for "
            f"{trial.get('nct_id', 'UNKNOWN')}"
        )

        raw_text = getattr(resp, "text", None)

        if raw_text:
            print(
                "[WARN] Raw Gemini response:",
                raw_text[:2000]
            )
        else:
            print("[WARN] Gemini response was empty.")

        fallback = _age_check(profile, trial)

        return (
            fallback,
            "Eligibility could not be fully assessed because the model did not return a valid structured response.",
            0,
        )

    # -----------------------------------------------------------------------
    # Normalize Source Text
    # -----------------------------------------------------------------------

    eligibility_text = trial.get("eligibility_text", "")
    patient_case = case

    elig_n = _norm(eligibility_text)
    case_n = _norm(patient_case)

    verified = []
    dropped = 0

    # -----------------------------------------------------------------------
    # Verify Every Gemini Criterion
    # -----------------------------------------------------------------------

    for c in out.criteria:

        criterion_quote = (c.criterion_quote or "").strip()
        patient_evidence = (c.patient_evidence_quote or "").strip()

        # ---------------------------------------------------------------
        # Verify Trial Quote
        # ---------------------------------------------------------------

        if not criterion_quote:

            dropped += 1

            print(
                f"[WARN] Dropped criterion with empty trial quote "
                f"for {trial.get('nct_id', 'UNKNOWN')}"
            )

            continue

        if _norm(criterion_quote) not in elig_n:

            dropped += 1

            print(
                f"[WARN] Dropped hallucinated/altered criterion for "
                f"{trial.get('nct_id', 'UNKNOWN')}: "
                f"{criterion_quote}"
            )

            continue

        # ---------------------------------------------------------------
        # Validate Impact
        # ---------------------------------------------------------------

        impact = c.impact

        if impact not in {
            "SUPPORTS",
            "BLOCKS",
            "UNKNOWN",
        }:

            impact = "UNKNOWN"
            patient_evidence = ""

        # ---------------------------------------------------------------
        # UNKNOWN must have no evidence
        # ---------------------------------------------------------------

        if impact == "UNKNOWN":

            patient_evidence = ""

        # ---------------------------------------------------------------
        # SUPPORTS / BLOCKS require patient evidence
        # ---------------------------------------------------------------

        else:

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

        # ---------------------------------------------------------------
        # Add Verified Criterion
        # ---------------------------------------------------------------

        verified.append(
            CriterionResult(
                source="TRIAL_TEXT",
                criterion_type=c.criterion_type,
                criterion_quote=criterion_quote,
                patient_evidence=patient_evidence,
                impact=impact,
                explanation=(c.explanation or "").strip(),
            )
        )

    # -----------------------------------------------------------------------
    # Final Result
    # -----------------------------------------------------------------------

    summary = (
        out.summary.strip()
        if out.summary
        else
        "The assessed trial criteria were compared against the provided patient case."
    )

    return (
        _age_check(profile, trial) + verified,
        summary,
        dropped,
    )


# ---------------------------------------------------------------------------
# Deterministic Final Verdict
# ---------------------------------------------------------------------------

def compute_verdict(
    criteria: list[CriterionResult]
) -> str:

    """
    The LLM NEVER determines the final eligibility label.

    Decision rules:

    BLOCKS present
        -> EXCLUDED

    Otherwise UNKNOWN present
        -> POSSIBLY_ELIGIBLE

    Otherwise
        -> ELIGIBLE
    """

    if any(
        c.impact == "BLOCKS"
        for c in criteria
    ):
        return "EXCLUDED"

    if (
        any(
            c.impact == "UNKNOWN"
            for c in criteria
        )
        or not criteria
    ):
        return "POSSIBLY_ELIGIBLE"

    return "ELIGIBLE"