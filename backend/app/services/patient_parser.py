import re
from google import genai
from google.genai import types
from app.config import settings
from app.schemas import PatientProfile

_client = None

def get_parser_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)
    return _client

SYSTEM = """You extract a structured profile from an anonymised patient case.
RULES:
- Extract ONLY facts explicitly written in the case. Never infer, assume or add medical knowledge.
- If a field is not stated, leave it empty / null / UNKNOWN.
- search_query: one or two sentences naming the main condition(s), stage/subtype, key biomarkers and
  relevant prior treatments, using only terms present in the case."""


def parse_patient(case: str) -> PatientProfile:
    resp = get_parser_client().models.generate_content(
        model=settings.gemini_model,
        contents=f"PATIENT CASE:\n{case}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=PatientProfile,
            temperature=0.0,
        ),
    )
    profile: PatientProfile = resp.parsed
    # Guard: an extracted age must literally appear in the source text.
    if profile.age_years is not None:
        if not re.search(rf"\b{int(profile.age_years)}\b", case):
            profile.age_years = None
    return profile