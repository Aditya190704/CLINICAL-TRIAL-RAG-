"""Mocked tests for workflow limits, validation, and failure behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.workflow import WorkflowError, run_adk_workflow, run_workflow_async
from app.schemas import (
    JudgeOutput, PatientExtractionOutput, PatientProfile, RefinementOutput,
)
from app.services.retriever import Candidate
from app.services.eligibility_judge import compute_verdict
from app.schemas import CriterionResult
from app.agents import adk_runtime
from app.agents.tools import ApprovedTrialRetrieval, RetrievalQuery


CASE = "A 55-year-old female with breast cancer receiving tamoxifen."


def extracted() -> PatientExtractionOutput:
    return PatientExtractionOutput(profile=PatientProfile(
        age_years=55,
        sex="FEMALE",
        primary_conditions=["breast cancer"],
        current_medications=["tamoxifen"],
        search_query="breast cancer tamoxifen",
    ))


def candidate(nct_id: str, score: float = 0.8) -> Candidate:
    return Candidate(nct_id=nct_id, rrf=0.02, best_sim=score, chunk_ids=[])


def trial(nct_id: str) -> dict:
    return {"nct_id": nct_id, "title": "Trial", "eligibility_text": "Age at least 18 years."}


def test_matching_uses_one_search_and_deduplicates_candidates():
    ids = ["NCT00000001", "NCT00000002"]
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate(ids[0]), candidate(ids[0], .7)]) as retrieval,
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()),
        patch("app.agents.workflow.trials", return_value={item: trial(item) for item in ids}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))

    assert retrieval.await_count == 1
    assert [item.nct_id for item in response.matches] == [ids[0]]


def test_refinement_agent_is_not_called_for_matching():
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate("NCT00000001")]) as retrieval,
        patch("app.agents.tasks.propose_refinement", new_callable=AsyncMock) as refinement,
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()),
        patch("app.agents.workflow.trials", return_value={"NCT00000001": trial("NCT00000001")}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        asyncio.run(run_workflow_async(CASE))
    assert retrieval.await_count == 1
    refinement.assert_not_awaited()


def test_assessment_cap_and_result_cap_are_enforced(monkeypatch):
    ids = ["NCT00000001", "NCT00000002", "NCT00000003"]
    monkeypatch.setattr("app.agents.workflow.settings.candidates_to_judge", 1)
    monkeypatch.setattr("app.agents.workflow.settings.final_results", 1)
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate(item) for item in ids]),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()) as assess,
        patch("app.agents.workflow.trials", return_value={item: trial(item) for item in ids}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))
    assert assess.await_count == 1
    assert len(response.matches) == 1


def test_sync_adapter_refuses_to_nest_inside_running_event_loop():
    async def call():
        with pytest.raises(RuntimeError, match="event loop is already running"):
            run_adk_workflow(CASE)
    asyncio.run(call())


def test_no_candidates_stops_without_refinement_or_assessment():
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[]),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock) as assess,
        patch("app.agents.workflow.trials", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))
    assert response.matches == []
    assert response.missing_key_facts
    assess.assert_not_awaited()


def test_unknown_criterion_never_improves_verdict_or_rank():
    unknown = CriterionResult(
        source="TRIAL_TEXT", criterion_type="INCLUSION", criterion_quote="Required detail",
        impact="UNKNOWN", explanation="Could not assess from available facts.",
    )
    assert compute_verdict([unknown]) == "POSSIBLY_ELIGIBLE"
    assert compute_verdict([]) == "POSSIBLY_ELIGIBLE"
    from app.agents.workflow import _criterion_priority
    assert _criterion_priority([]) < _criterion_priority([unknown])


def test_agent_output_schemas_reject_unexpected_fields():
    with pytest.raises(ValueError, match="Unexpected"):
        PatientExtractionOutput.model_validate({
            "profile": {"search_query": "cancer", "action": "call arbitrary tool"},
        })
    with pytest.raises(ValueError):
        RefinementOutput.model_validate({"refine": True, "tool": "shell"})
    with pytest.raises(ValueError):
        RetrievalQuery(query="breast cancer", action="other")


def test_approved_retrieval_tool_enforces_two_call_bound():
    profile = extracted().profile
    tool = ApprovedTrialRetrieval(case=CASE, profile=profile)
    with patch("app.agents.tools.retrieve", return_value=[]):
        async def search_twice():
            await tool.search("breast cancer")
            await tool.search("tamoxifen")
            with pytest.raises(ValueError, match="retrieval limit"):
                await tool.search("breast cancer")
        asyncio.run(search_twice())
    assert tool.calls == 2


def test_adk_session_is_created_and_deleted_around_validated_output():
    class FakeEvent:
        content = type("Content", (), {"parts": [type("Part", (), {"text": '{"refine": false, "search_query": ""}'})()]})()
        def is_final_response(self):
            return True

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass
        async def run_async(self, **_kwargs):
            yield FakeEvent()

    class FakeSessions:
        async def create_session(self, **_kwargs):
            return None
        async def delete_session(self, **_kwargs):
            self.deleted = True

    async def run():
        service = FakeSessions()
        client = MagicMock()
        client.aio.aclose = AsyncMock()
        with (
            patch.object(adk_runtime, "LlmAgent"),
            patch.object(adk_runtime, "Gemini"),
            patch.object(adk_runtime, "Runner", FakeRunner),
            patch.object(adk_runtime, "InMemorySessionService", return_value=service),
            patch.object(adk_runtime.genai, "Client", return_value=client) as create_client,
        ):
            result = await adk_runtime.run_structured_agent(
                name="test_agent", instruction="untrusted data", data={"text": "test"},
                output_schema=RefinementOutput,
            )
        assert result.refine is False
        assert service.deleted is True
        create_client.assert_called_once()
        assert create_client.call_args.kwargs["enterprise"] is True
        client.aio.aclose.assert_awaited_once()
        client.close.assert_called_once()
    asyncio.run(run())

