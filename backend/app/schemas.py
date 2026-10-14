
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Shared model configuration
# ---------------------------------------------------------------------------

class APIModel(BaseModel):
    """Base model for API data structures."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


# ---------------------------------------------------------------------------
# Match request
# ---------------------------------------------------------------------------

class MatchRequest(APIModel):
    patient_case: str = Field(
        min_length=40,
        max_length=8000,
        description="An anonymised patient case, between 40 and 8000 characters.",
    )

    @field_validator("patient_case")
    @classmethod
    def validate_patient_case(cls, value: str) -> str:
        value = value.strip()

        if len(value) < 40:
            raise ValueError(
                "Patient case must contain at least 40 non-whitespace characters."
            )

        if len(value) > 8000:
            raise ValueError(
                "Patient case must contain no more than 8000 characters."
            )

        return value


# ---------------------------------------------------------------------------
# Patient profile
# ---------------------------------------------------------------------------

class PatientProfile(APIModel):
    """Explicit facts extracted from the anonymised patient case."""

    age_years: float | None = Field(
        default=None,
        ge=0,
        description="Age in years, only when supported by the patient case.",
    )

    sex: Literal["MALE", "FEMALE", "UNKNOWN"] = "UNKNOWN"

    primary_conditions: list[str] = Field(default_factory=list)
    comorbidities: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    prior_treatments: list[str] = Field(default_factory=list)

    key_findings: list[str] = Field(
        default_factory=list,
        description=(
            "Explicitly stated laboratory results, staging, biomarkers, "
            "performance status, and other relevant findings."
        ),
    )

    search_query: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Condition-focused retrieval query using only facts stated "
            "in the patient case."
        ),
    )


# ---------------------------------------------------------------------------
# Eligibility judge output
# ---------------------------------------------------------------------------

class JudgedCriterion(APIModel):
    """Raw structured output from the Gemini eligibility judge."""

    criterion_type: Literal["INCLUSION", "EXCLUSION"]

    criterion_quote: str = Field(
        description="Verbatim, contiguous text from the supplied trial criteria."
    )

    patient_evidence_quote: str = Field(
        default="",
        description=(
            "Verbatim evidence from the supplied patient case, "
            "or an empty string when evidence is unavailable."
        ),
    )

    impact: Literal["SUPPORTS", "BLOCKS", "UNKNOWN"]

    explanation: str = Field(
        description="Short explanation grounded in the supplied evidence."
    )


class JudgeOutput(APIModel):
    """Structured output returned by the eligibility judge."""

    criteria: list[JudgedCriterion] = Field(default_factory=list)

    summary: str = Field(
        default="Insufficient evidence was provided to assess the trial criteria."
    )


# ---------------------------------------------------------------------------
# Verified eligibility evidence
# ---------------------------------------------------------------------------


class CriterionResult(APIModel):
    source: Literal["TRIAL_TEXT", "STRUCTURED"]
    criterion_type: Literal["INCLUSION", "EXCLUSION"]
    criterion_quote: str
    patient_evidence: str | None = None
    impact: Literal["SUPPORTS", "BLOCKS", "UNKNOWN"]
    explanation: str


class Passage(APIModel):
    """Retrieved trial passage supporting relevance or follow-up answers."""

    chunk_type: str = Field(default="unknown")
    text: str = Field(default="", max_length=5000)


# ---------------------------------------------------------------------------
# Trial match response
# ---------------------------------------------------------------------------

class TrialMatch(APIModel):
    rank: int = Field(ge=1)

    nct_id: str = Field(min_length=1)
    title: str = Field(min_length=1)

    url: str = Field(
        description="Official ClinicalTrials.gov study record URL."
    )

    status: str = Field(default="Unknown")
    phases: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    sponsor: str | None = None
    locations: list[str] = Field(default_factory=list)

    relevance_score: float = Field(
        ge=0,
        le=1,
        description=(
            "Retrieval similarity score, not a probability of eligibility."
        ),
    )

    verdict: Literal[
        "ELIGIBLE",
        "POSSIBLY_ELIGIBLE",
        "EXCLUDED",
    ]

    summary: str = Field(default="")

    criteria: list[CriterionResult] = Field(default_factory=list)

    dropped_unverified: int = Field(
        default=0,
        ge=0,
        description="Number of unverified criterion statements discarded.",
    )

    passages: list[Passage] = Field(default_factory=list)


class MatchResponse(APIModel):
    patient_profile: PatientProfile
    matches: list[TrialMatch] = Field(default_factory=list)

    disclaimer: str = Field(default="")

    latency_seconds: float = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Chat request
# ---------------------------------------------------------------------------

class ChatRequest(APIModel):
    """Follow-up question about the selected trial shortlist."""

    question: str = Field(
        min_length=1,
        max_length=4000,
        description="A question about the selected clinical trials.",
    )

    trial_ids: list[str] = Field(
        min_length=1,
        description="NCT IDs returned by the matching workflow.",
    )

    patient_case: str | None = Field(
        default=None,
        max_length=8000,
    )

    session_id: str | None = Field(
        default=None,
        max_length=200,
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Question must not be empty.")

        return value

    @field_validator("trial_ids")
    @classmethod
    def normalize_trial_ids(cls, value: list[str]) -> list[str]:
        normalized = []

        for trial_id in value:
            trial_id = trial_id.strip().upper()

            if not trial_id:
                continue

            if trial_id not in normalized:
                normalized.append(trial_id)

        if not normalized:
            raise ValueError(
                "At least one non-empty trial ID must be provided."
            )

        return normalized

    @field_validator("patient_case")
    @classmethod
    def normalize_optional_patient_case(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()
        return value or None

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()
        return value or None


# ---------------------------------------------------------------------------
# Chat citations and response
# ---------------------------------------------------------------------------

class Citation(APIModel):
    """A source reference that the frontend can render as a clickable link."""

    nct_id: str = Field(min_length=1)

    trial_title: str | None = None

    section: str = Field(default="Trial evidence")

    excerpt: str = Field(
        default="",
        max_length=2000,
        description="Short excerpt from the retrieved trial source.",
    )

    url: str = Field(
        description="Official URL for the cited clinical trial."
    )


class ChatResponse(APIModel):
    answer: str = Field(min_length=1)

    citations: list[Citation] = Field(default_factory=list)

    missing_info: str | None = None

    session_id: str | None = None
