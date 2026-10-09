from typing import Literal, Optional
from pydantic import BaseModel, Field


class MatchRequest(BaseModel):
    patient_case: str = Field(min_length=40, max_length=8000)


# ---- patient profile (LLM-extracted, explicit facts only) ----
class PatientProfile(BaseModel):
    age_years: Optional[float] = None
    sex: Literal["MALE", "FEMALE", "UNKNOWN"] = "UNKNOWN"
    primary_conditions: list[str] = []
    comorbidities: list[str] = []
    current_medications: list[str] = []
    prior_treatments: list[str] = []
    key_findings: list[str] = Field(default=[], description="labs, staging, biomarkers, performance status")
    search_query: str = Field(description="Condition-focused retrieval query built only from stated facts")


# ---- judge output (LLM) ----
class JudgedCriterion(BaseModel):
    criterion_type: Literal["INCLUSION", "EXCLUSION"]
    criterion_quote: str = Field(description="Verbatim, contiguous text copied from the trial criteria")
    patient_evidence_quote: str = Field(description="Verbatim text from the patient case, or empty string")
    impact: Literal["SUPPORTS", "BLOCKS", "UNKNOWN"]
    explanation: str


class JudgeOutput(BaseModel):
    criteria: list[JudgedCriterion]
    summary: str


# ---- API response ----
class CriterionResult(BaseModel):
    source: Literal["TRIAL_TEXT", "STRUCTURED"]
    criterion_type: Literal["INCLUSION", "EXCLUSION"]
    criterion_quote: str
    patient_evidence: str
    impact: Literal["SUPPORTS", "BLOCKS", "UNKNOWN"]
    explanation: str


class Passage(BaseModel):
    chunk_type: str
    text: str


class TrialMatch(BaseModel):
    rank: int
    nct_id: str
    title: str
    url: str
    status: str
    phases: list[str]
    conditions: list[str]
    sponsor: Optional[str]
    locations: list[str]
    relevance_score: float
    verdict: Literal["ELIGIBLE", "POSSIBLY_ELIGIBLE", "EXCLUDED"]
    summary: str
    criteria: list[CriterionResult]
    dropped_unverified: int
    passages: list[Passage]


class MatchResponse(BaseModel):
    patient_profile: PatientProfile
    matches: list[TrialMatch]
    disclaimer: str
    latency_seconds: float