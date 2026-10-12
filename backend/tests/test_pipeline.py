"""Unit and integration tests for Clinical Trial RAG pipeline and FastAPI endpoints."""
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CriterionResult, PatientProfile, MatchResponse
from app.services.pipeline import run, PHI, ORDER
from app.services.retriever import Candidate


client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. PHI Detection Tests
# ---------------------------------------------------------------------------

def test_phi_detection():
    """Detects SSNs, emails, and phone numbers."""
    assert PHI.search("Patient email is doctor@example.com") is not None
    assert PHI.search("SSN: 123-45-6789") is not None
    assert PHI.search("Call 555-123-4567") is not None
    assert PHI.search("Patient has 55-year-old stage IV adenocarcinoma.") is None


def test_pipeline_phi_rejection():
    """Pipeline rejects cases with PHI."""
    with pytest.raises(ValueError, match="identifiers"):
        run("Patient SSN 123-45-6789 has non-small cell lung cancer.")


# ---------------------------------------------------------------------------
# 2. Pipeline Integration & Verdict Ordering Tests
# ---------------------------------------------------------------------------

@patch("app.services.pipeline.parse_patient")
@patch("app.services.pipeline.retrieve")
@patch("app.services.pipeline.judge")
@patch("app.services.pipeline.trials")
@patch("app.services.pipeline.chunks")
def test_pipeline_run_integration(mock_chunks, mock_trials, mock_judge, mock_retrieve, mock_parse):
    """Pipeline runs end-to-end with mocked components and preserves schemas."""
    mock_parse.return_value = PatientProfile(
        age_years=55.0,
        sex="FEMALE",
        primary_conditions=["breast cancer"],
        search_query="breast cancer HER2 positive",
    )

    mock_retrieve.return_value = [
        Candidate(nct_id="NCT001", rrf=0.033, best_sim=0.88, chunk_ids=["NCT001::overview::0"]),
        Candidate(nct_id="NCT002", rrf=0.025, best_sim=0.75, chunk_ids=["NCT002::overview::0"]),
    ]

    mock_trials.return_value = {
        "NCT001": {
            "nct_id": "NCT001",
            "title": "Study 1",
            "status": "RECRUITING",
            "phases": ["PHASE2"],
            "conditions": ["breast cancer"],
            "sponsor": "Sponsor A",
            "locations": ["Hospital A"],
        },
        "NCT002": {
            "nct_id": "NCT002",
            "title": "Study 2",
            "status": "RECRUITING",
            "phases": ["PHASE3"],
            "conditions": ["breast cancer"],
            "sponsor": "Sponsor B",
            "locations": ["Hospital B"],
        },
    }

    mock_chunks.return_value = {
        "NCT001::overview::0": {"nct_id": "NCT001", "type": "overview", "text": "Trial 1 overview text"},
        "NCT002::overview::0": {"nct_id": "NCT002", "type": "overview", "text": "Trial 2 overview text"},
    }

    # First trial is POSSIBLY_ELIGIBLE (contains UNKNOWN criteria), second is ELIGIBLE
    mock_judge.side_effect = [
        (
            [CriterionResult(source="TRIAL_TEXT", criterion_type="INCLUSION", criterion_quote="HER2+", patient_evidence="", impact="UNKNOWN", explanation="Missing HER2 lab")],
            "Summary 1",
            0,
        ),
        (
            [CriterionResult(source="TRIAL_TEXT", criterion_type="INCLUSION", criterion_quote="Age >= 18", patient_evidence="Age 55", impact="SUPPORTS", explanation="Age matches")],
            "Summary 2",
            0,
        ),
    ]

    case = "Patient is a 55-year-old female presenting with infiltrating ductal carcinoma."
    resp: MatchResponse = run(case)

    assert resp.patient_profile.sex == "FEMALE"
    assert len(resp.matches) == 2
    # ELIGIBLE trial should be ranked first before POSSIBLY_ELIGIBLE per ORDER
    assert resp.matches[0].nct_id == "NCT002"
    assert resp.matches[0].verdict == "ELIGIBLE"
    assert resp.matches[1].nct_id == "NCT001"
    assert resp.matches[1].verdict == "POSSIBLY_ELIGIBLE"
    assert resp.matches[0].relevance_score == 0.75
    assert len(resp.matches[0].passages) == 1


# ---------------------------------------------------------------------------
# 3. FastAPI Endpoint Compatibility Tests
# ---------------------------------------------------------------------------

def test_health_endpoint():
    """Health check endpoint returns status and indexed trial count."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "trials_indexed" in data


@patch("app.main.pipeline.run")
def test_match_endpoint_success(mock_run):
    """POST /api/match returns 200 with valid MatchResponse."""
    mock_run.return_value = MatchResponse(
        patient_profile=PatientProfile(search_query="test condition"),
        matches=[],
        disclaimer="Research only",
        latency_seconds=1.2,
    )
    payload = {
        "patient_case": "A 62-year-old male with persistent cough and shortness of breath diagnosed with adenocarcinoma."
    }
    resp = client.post("/api/match", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "patient_profile" in data
    assert "matches" in data
    assert "disclaimer" in data
    assert "latency_seconds" in data


def test_match_endpoint_case_too_short():
    """POST /api/match rejects case shorter than 40 chars."""
    resp = client.post("/api/match", json={"patient_case": "Too short"})
    assert resp.status_code == 422  # Pydantic validation error


@patch("app.main.pipeline.run")
def test_match_endpoint_permission_error_handling(mock_run):
    """PermissionError returns 503 with safe error message."""
    mock_run.side_effect = PermissionError("GCP IAM permission denied")
    payload = {
        "patient_case": "A 62-year-old male with persistent cough and shortness of breath diagnosed with adenocarcinoma."
    }
    resp = client.post("/api/match", json=payload)
    assert resp.status_code == 503
    assert "BigQuery IAM permissions" in resp.json()["detail"]

