"""Mocked tests for workflow limits, validation, and failure behavior."""

import asyncio
import statistics
import time
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


def test_supported_subtype_stage_biomarker_and_treatments_reach_retrieval():
    case = "A 55-year-old woman with stage II breast cancer, HER2 positive, treated with tamoxifen, ECOG performance status 1."
    profile = PatientProfile(
        age_years=55,
        sex="FEMALE",
        primary_conditions=["breast cancer"],
        prior_treatments=["tamoxifen"],
        key_findings=["stage II", "HER2 positive", "ECOG performance status 1"],
        search_query="breast cancer",
    )
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=PatientExtractionOutput(profile=profile)),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, side_effect=[[candidate("NCT00000001", .2)], []]) as retrieval,
        patch("app.agents.workflow.propose_refinement", new_callable=AsyncMock, return_value=RefinementOutput(refine=True, search_query="breast cancer stage II HER2 positive ECOG performance status 1 tamoxifen")),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()),
        patch("app.agents.workflow.trials", return_value={"NCT00000001": trial("NCT00000001")}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        asyncio.run(run_workflow_async(case))
    assert retrieval.await_count == 2
    query = retrieval.await_args_list[1].args[0]
    assert all(term in query.casefold() for term in ("breast cancer", "stage ii", "her2 positive", "tamoxifen", "ecog performance status 1"))


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


def test_assessment_hard_cap_and_three_result_limit(monkeypatch):
    ids = [f"NCT000000{i:02d}" for i in range(1, 13)]
    monkeypatch.setattr("app.agents.workflow.settings.candidates_to_judge", 100)
    monkeypatch.setattr("app.agents.workflow.settings.final_results", 20)
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate(item, .8) for item in ids]),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()) as assess,
        patch("app.agents.workflow.trials", return_value={item: trial(item) for item in ids}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))
    assert assess.await_count == 10
    assert len(response.matches) == 3


def test_sync_adapter_refuses_to_nest_inside_running_event_loop():
    async def call():
        with pytest.raises(RuntimeError, match="event loop is already running"):
            run_adk_workflow(CASE)
    asyncio.run(call())


def test_no_candidates_stops_without_refinement_or_assessment():
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[]),
        patch("app.agents.workflow.propose_refinement", new_callable=AsyncMock, return_value=RefinementOutput()),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock) as assess,
        patch("app.agents.workflow.trials", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))
    assert response.matches == []
    assert response.result_message and "in this search" in response.result_message
    assert response.missing_key_facts
    assess.assert_not_awaited()


def test_weak_retrieval_refines_once_and_merges_candidates():
    ids = ["NCT00000001", "NCT00000002"]
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch(
            "app.agents.workflow.ApprovedTrialRetrieval.search",
            new_callable=AsyncMock,
            side_effect=[[candidate(ids[0], .2)], [candidate(ids[1], .8)]],
        ) as retrieval,
        patch(
            "app.agents.workflow.propose_refinement",
            new_callable=AsyncMock,
            return_value=RefinementOutput(refine=True, search_query="breast cancer tamoxifen"),
        ) as refinement,
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()),
        patch("app.agents.workflow.trials", return_value={item: trial(item) for item in ids}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))
    assert retrieval.await_count == 2
    refinement.assert_awaited_once()
    assert {item.nct_id for item in response.matches} == set(ids)


def test_refinement_without_new_supported_terms_does_not_repeat_retrieval():
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate("NCT00000001", .2)]) as retrieval,
        patch("app.agents.workflow.propose_refinement", new_callable=AsyncMock, return_value=RefinementOutput(refine=True, search_query="breast cancer")),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=JudgeOutput()),
        patch("app.agents.workflow.trials", return_value={"NCT00000001": trial("NCT00000001")}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        asyncio.run(run_workflow_async(CASE))
    assert retrieval.await_count == 1


def test_assessments_run_concurrently_with_configured_bound(monkeypatch):
    ids = [f"NCT0000000{i}" for i in range(1, 5)]
    monkeypatch.setattr("app.agents.workflow.settings.adk_concurrency", 2)
    active = 0
    maximum = 0

    async def assess(**_kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(.01)
        active -= 1
        return JudgeOutput()

    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate(item, .8) for item in ids]),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, side_effect=assess),
        patch("app.agents.workflow.trials", return_value={item: trial(item) for item in ids}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        asyncio.run(run_workflow_async(CASE))
    assert maximum == 2


def test_mocked_assessment_latency_improves_with_bounded_concurrency():
    ids = [f"NCT0000000{i}" for i in range(1, 7)]
    index = {item: trial(item) for item in ids}

    async def delayed_assess(**_kwargs):
        await asyncio.sleep(.03)
        return JudgeOutput()

    async def measure(concurrency):
        with (
            patch("app.agents.workflow.settings.adk_concurrency", concurrency),
            patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
            patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate(item, .8) for item in ids]),
            patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, side_effect=delayed_assess),
            patch("app.agents.workflow.trials", return_value=index),
            patch("app.agents.workflow.chunks", return_value={}),
        ):
            started = time.perf_counter()
            await run_workflow_async(CASE)
            return time.perf_counter() - started

    async def compare():
        serial = [await measure(1) for _ in range(3)]
        concurrent = [await measure(6) for _ in range(3)]
        return statistics.median(serial), statistics.median(concurrent)

    serial_duration, concurrent_duration = asyncio.run(compare())
    print(
        "mocked_full_workflow_median_ms "
        f"concurrency_1={serial_duration * 1000:.1f} "
        f"concurrency_6={concurrent_duration * 1000:.1f}"
    )
    assert concurrent_duration < serial_duration * .8


def test_overall_timeout_cancels_workflow_tasks(monkeypatch):
    cancelled = False

    async def blocked_steps(*_args, **_kwargs):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr("app.agents.workflow.MAX_WORKFLOW_SECONDS", .01)
    with patch("app.agents.workflow._run_steps", new=blocked_steps):
        with pytest.raises(WorkflowError) as error:
            asyncio.run(run_workflow_async(CASE))
    assert error.value.code == "WORKFLOW_TIMEOUT"
    assert cancelled


def test_verified_exclusion_is_separated_from_shortlist():
    ids = ["NCT00000001"]
    excluded_trial = {
        **trial(ids[0]),
        "eligibility_text": "Age under 40 years.",
    }
    judge_output = JudgeOutput(criteria=[{
        "criterion_type": "INCLUSION",
        "criterion_quote": "Age under 40 years.",
        "patient_evidence_quote": "55-year-old",
        "impact": "BLOCKS",
        "explanation": "The documented age exceeds the stated limit.",
    }])
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=extracted()),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate(ids[0], .9)]),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=judge_output),
        patch("app.agents.workflow.trials", return_value={ids[0]: excluded_trial}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(CASE))
    assert response.matches == []
    assert response.ruled_out_trials[0].nct_id == ids[0]
    assert "Age under 40 years." in response.ruled_out_trials[0].reason


def test_conflicting_age_cannot_be_used_as_assessment_evidence():
    case = "Patient age 55 years old and age 67 years old with breast cancer."
    output = JudgeOutput(criteria=[{
        "criterion_type": "INCLUSION",
        "criterion_quote": "Age must be over 18 years.",
        "patient_evidence_quote": "67 years old",
        "impact": "SUPPORTS",
        "explanation": "The patient is an adult.",
    }])
    with (
        patch("app.agents.workflow.extract_patient", new_callable=AsyncMock, return_value=PatientExtractionOutput(profile=PatientProfile(primary_conditions=["breast cancer"], search_query="breast cancer"))),
        patch("app.agents.workflow.ApprovedTrialRetrieval.search", new_callable=AsyncMock, return_value=[candidate("NCT00000001", .9)]),
        patch("app.agents.workflow.assess_trial", new_callable=AsyncMock, return_value=output) as assess,
        patch("app.agents.workflow.trials", return_value={"NCT00000001": {**trial("NCT00000001"), "eligibility_text": "Age must be over 18 years."}}),
        patch("app.agents.workflow.chunks", return_value={}),
    ):
        response = asyncio.run(run_workflow_async(case))

    assessment_case = assess.await_args.kwargs["case"]
    assert "55 years old" not in assessment_case
    assert "67 years old" not in assessment_case
    assert response.conflicting_facts
    assert response.matches[0].verdict == "COULD_NOT_ASSESS"


def test_unknown_criterion_never_improves_verdict_or_rank():
    unknown = CriterionResult(
        source="TRIAL_TEXT", criterion_type="INCLUSION", criterion_quote="Required detail",
        impact="UNKNOWN", explanation="Could not assess from available facts.",
    )
    assert compute_verdict([unknown]) == "COULD_NOT_ASSESS"
    assert compute_verdict([]) == "COULD_NOT_ASSESS"
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

