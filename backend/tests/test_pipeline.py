"""Unit and integration tests for Clinical Trial RAG pipeline and FastAPI endpoints."""
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_dependency import require_firebase_user
from app.schemas import (
    CriterionResult, JudgeOutput, JudgedCriterion, MatchResponse,
    PatientExtractionOutput, PatientProfile, RefinementOutput,
)
from app.services.pipeline import run, PHI, ORDER
from app.services.retriever import Candidate


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_api_user():
    """Keep route tests authenticated without contacting Firebase or Firestore."""
    app.dependency_overrides[require_firebase_user] = lambda: {
        "uid": "test-user",
        "email": "test@example.com",
        "display_name": "Test User",
    }
    with (
        patch("app.main.user_data.create_session", return_value={"id": "test-session"}),
        patch("app.main.user_data.get_session", return_value={
            "id": "test-session",
            "matchedTrialIds": ["NCT00000001"],
        }),
        patch("app.main.user_data.save_search_query", return_value=True),
        patch("app.main.user_data.mark_search_failed"),
        patch("app.main.user_data.save_match_result", return_value=True),
        patch("app.main.user_data.load_chat_turn", return_value=None),
        patch("app.main.user_data.persist_chat_turn", return_value=True),
    ):
        yield
    app.dependency_overrides.pop(require_firebase_user, None)


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


def test_identifier_screening_precedes_urgent_screen():
    with patch("app.services.pipeline.screen_urgent_case") as screen:
        with pytest.raises(ValueError, match="identifiers"):
            run("Patient email alice@example.com has severe chest pain and needs immediate review.")
    screen.assert_not_called()


def test_urgent_case_returns_notice_without_workflow_calls():
    with patch("app.services.pipeline.run_workflow_async", new_callable=AsyncMock) as workflow:
        response = client.post("/api/match", json={
            "patient_case": "Patient reports severe chest pain and sudden difficulty breathing today."
        })
    assert response.status_code == 200
    data = response.json()
    assert data["emergency_notice"]
    assert data["matches"] == []
    assert data["disclaimer"]
    workflow.assert_not_awaited()


def test_match_persists_validated_query_on_owned_session():
    case = "62-year-old patient with stage III lung cancer and documented EGFR mutation."
    response = MatchResponse(
        patient_profile=PatientProfile(search_query="stage III lung cancer EGFR"),
        matches=[],
        disclaimer="For clinical review.",
    )
    with (
        patch("app.main.user_data.save_search_query", return_value=True) as save_query,
        patch("app.main.pipeline.run_async", new_callable=AsyncMock, return_value=response),
    ):
        result = client.post("/api/match", json={"patient_case": case, "session_id": "test-session"})
    assert result.status_code == 200
    save_query.assert_called_once_with("test-user", "test-session", case)
    assert result.json()["session_id"] == "test-session"


def test_match_does_not_persist_direct_identifiers():
    case = "Patient email clinician@example.org has stage III lung cancer and needs matching."
    with patch("app.main.user_data.save_search_query") as save_query:
        result = client.post("/api/match", json={"patient_case": case})
    assert result.status_code == 400
    save_query.assert_not_called()


def test_session_read_rejects_a_session_outside_the_authenticated_scope():
    with patch("app.main.user_data.get_session", return_value=None) as get_owned_session:
        result = client.get("/api/sessions/another-users-session")
    assert result.status_code == 403
    get_owned_session.assert_called_once_with("test-user", "another-users-session")


def test_urgent_screen_failure_fails_closed_and_does_not_log_input(caplog):
    private_text = "patient-private-screen-text"
    payload = {"patient_case": f"{private_text} with a sufficiently long ordinary case narrative for validation."}
    with (
        patch("app.services.pipeline.screen_urgent_case", side_effect=RuntimeError(private_text)),
        patch("app.services.pipeline.run_workflow_async", new_callable=AsyncMock) as workflow,
    ):
        response = client.post("/api/match", json=payload)
    assert response.status_code == 500
    assert private_text not in caplog.text
    workflow.assert_not_awaited()


# ---------------------------------------------------------------------------
# 2. Pipeline Integration & Verdict Ordering Tests
# ---------------------------------------------------------------------------


@patch("app.agents.workflow.extract_patient", new_callable=AsyncMock)
@patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock)
@patch("app.agents.workflow.assess_trial", new_callable=AsyncMock)
@patch("app.agents.workflow.trials")
@patch("app.agents.workflow.chunks")
def test_pipeline_run_integration(mock_chunks, mock_trials, mock_assess, mock_retrieve, mock_extract):
    """Pipeline runs end-to-end with mocked components and preserves schemas."""
    mock_extract.return_value = PatientExtractionOutput(
        profile=PatientProfile(
            age_years=55.0,
            sex="FEMALE",
            primary_conditions=["breast cancer"],
            search_query="breast cancer",
        )
    )

    mock_retrieve.return_value = [
        Candidate(nct_id="NCT00000001", rrf=0.033, best_sim=0.88, chunk_ids=["NCT00000001::overview::0"]),
        Candidate(nct_id="NCT00000002", rrf=0.025, best_sim=0.75, chunk_ids=["NCT00000002::overview::0"]),
    ]

    mock_trials.return_value = {
        "NCT00000001": {
            "nct_id": "NCT00000001",
            "title": "Study 1",
            "eligibility_text": "HER2-positive disease is required.",
            "status": "RECRUITING",
            "phases": ["PHASE2"],
            "conditions": ["breast cancer"],
            "sponsor": "Sponsor A",
            "locations": ["Hospital A"],
        },
        "NCT00000002": {
            "nct_id": "NCT00000002",
            "title": "Study 2",
            "eligibility_text": "Age at least 18 years.",
            "status": "RECRUITING",
            "phases": ["PHASE3"],
            "conditions": ["breast cancer"],
            "sponsor": "Sponsor B",
            "locations": ["Hospital B"],
        },
    }

    mock_chunks.return_value = {
        "NCT00000001::overview::0": {"nct_id": "NCT00000001", "type": "overview", "text": "Trial 1 overview text"},
        "NCT00000002::overview::0": {"nct_id": "NCT00000002", "type": "overview", "text": "Trial 2 overview text"},
    }

    async def assessment(*, trial, **kwargs):
        if trial["nct_id"] == "NCT00000001":
            return JudgeOutput(criteria=[JudgedCriterion(
                criterion_type="INCLUSION", criterion_quote="HER2-positive disease is required.",
                patient_evidence_quote="", impact="UNKNOWN", explanation="Missing biomarker detail.",
            )])
        return JudgeOutput(criteria=[JudgedCriterion(
            criterion_type="INCLUSION", criterion_quote="Age at least 18 years.",
            patient_evidence_quote="55-year-old", impact="SUPPORTS", explanation="Age is stated.",
        )])
    mock_assess.side_effect = assessment

    case = "Patient is a 55-year-old female with breast cancer, infiltrating ductal carcinoma."
    resp: MatchResponse = run(case)

    assert resp.patient_profile.sex == "FEMALE"
    assert len(resp.matches) == 2
    # Fewer unresolved criteria ranks before similarity; neither verdict
    # establishes eligibility.
    assert resp.matches[0].nct_id == "NCT00000002"
    assert resp.matches[0].verdict == "POSSIBLY_ELIGIBLE"
    assert "do not establish eligibility" in resp.matches[0].summary
    assert resp.matches[1].nct_id == "NCT00000001"
    assert resp.matches[1].verdict == "COULD_NOT_ASSESS"
    assert resp.matches[1].relevance_score == 0.88
    assert len(resp.matches[1].passages) == 1


# ---------------------------------------------------------------------------
# 3. FastAPI Endpoint Compatibility Tests
# ---------------------------------------------------------------------------

@patch("app.main.trials", return_value=[])
def test_health_endpoint(_mock_trials):
    """Health check endpoint returns status and indexed trial count."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "trials_indexed" in data


@patch("app.main.pipeline.run_async", new_callable=AsyncMock)
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
    assert data["missing_key_facts"] == []
    assert data["conflicting_facts"] == []
    assert data["emergency_notice"] is None


def test_match_endpoint_case_too_short():
    """POST /api/match rejects case shorter than 40 chars."""
    resp = client.post("/api/match", json={"patient_case": "Too short"})
    assert resp.status_code == 422  # Pydantic validation error


@patch("app.main.pipeline.run_async", new_callable=AsyncMock)
def test_match_endpoint_permission_error_handling(mock_run):
    """PermissionError returns 503 with safe error message."""
    mock_run.side_effect = PermissionError("GCP IAM permission denied")
    payload = {
        "patient_case": "A 62-year-old male with persistent cough and shortness of breath diagnosed with adenocarcinoma."
    }
    resp = client.post("/api/match", json=payload)
    assert resp.status_code == 503
    assert "BigQuery IAM permissions" in resp.json()["detail"]


def test_match_failure_does_not_log_or_echo_provider_details(caplog):
    secret = "private-clinical-text-marker"
    with patch("app.main.pipeline.run_async", new_callable=AsyncMock, side_effect=RuntimeError(secret)):
        response = client.post("/api/match", json={
            "patient_case": "A 62-year-old male with adenocarcinoma and a private clinical detail marker."
        })
    assert response.status_code == 500
    assert secret not in caplog.text
    assert secret not in response.text


@patch("app.main.chat_answer", new_callable=AsyncMock)
def test_chat_response_keeps_citations_and_client_session_id(mock_chat):
    mock_chat.return_value = {
        "answer": "The trial passage does not state this detail.",
        "citations": [{
            "nct_id": "NCT00000001", "trial_title": "Trial", "section": "Eligibility",
            "excerpt": "Adults are eligible.", "url": "https://clinicaltrials.gov/study/NCT00000001",
        }],
        "missing_info": "Not specified in the selected trial text.",
    }
    response = client.post("/api/trials/chat", json={
        "question": "What is this trial's age requirement?",
        "trial_ids": ["NCT00000001"],
        "session_id": "client-local-id",
    })
    assert response.status_code == 200
    assert response.json()["citations"][0]["nct_id"] == "NCT00000001"
    assert response.json()["session_id"] == "client-local-id"


def test_chat_error_does_not_log_or_echo_question(caplog):
    secret = "question-private-clinical-marker"
    with patch("app.main.chat_answer", new_callable=AsyncMock, side_effect=RuntimeError(secret)):
        response = client.post("/api/trials/chat", json={
            "question": f"{secret} what does the trial say about eligibility?",
            "trial_ids": ["NCT00000001"],
            "session_id": "test-session",
        })
    assert response.status_code == 500
    assert secret not in caplog.text
    assert secret not in response.text
