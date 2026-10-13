
# backend/app/agents/workflow.py

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent, SequentialAgent, ParallelAgent
from google.adk.agents import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.config import settings
from app.schemas import (
    PatientProfile,
    CriterionResult,
    Passage,
    TrialMatch,
    MatchResponse,
)
from app.services.patient_parser import parse_patient
from app.services.retriever import retrieve
from app.services.eligibility_judge import judge, compute_verdict
from app.services.trial_store import trials, chunks


DISCLAIMER = (
    "Research decision-support only. Not medical advice. All eligibility "
    "reasoning is limited to the supplied case and registry text; confirm "
    "with the trial's contacts before referral."
)

VERDICT_ORDER = {
    "ELIGIBLE": 0,
    "POSSIBLY_ELIGIBLE": 1,
    "EXCLUDED": 2,
}


def stage_event(ctx: InvocationContext, agent_name: str, state_delta=None):
    """Build a standard ADK event, optionally updating session state."""
    return Event(
        invocation_id=ctx.invocation_id,
        author=agent_name,
        content=types.Content(
            role="model",
            parts=[types.Part(text=f"{agent_name} completed.")],
        ),
        actions=EventActions(state_delta=state_delta or {}),
    )


class PatientParserAgent(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        case = ctx.session.state["patient_case"]

        profile = await asyncio.to_thread(parse_patient, case)

        # Keep ADK state JSON-serializable.
        yield stage_event(
            ctx,
            self.name,
            {"patient_profile": profile.model_dump(mode="json")},
        )


class TrialRetrievalAgent(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        profile = PatientProfile.model_validate(
            ctx.session.state["patient_profile"]
        )
        case = ctx.session.state["patient_case"]

        candidates = await asyncio.to_thread(
            retrieve, [profile.search_query, case[:2000]]
        )

        limit = max(0, settings.candidates_to_judge)
        candidate_records = [
            {
                "nct_id": candidate.nct_id,
                "rrf": float(candidate.rrf),
                "best_sim": float(candidate.best_sim),
                "chunk_ids": list(candidate.chunk_ids),
            }
            for candidate in candidates[:limit]
        ]

        yield stage_event(
            ctx,
            self.name,
            {"trial_candidates": candidate_records},
        )


class TrialEligibilityAgent(BaseAgent):
    """Evaluate one retrieved trial using the existing eligibility judge."""

    nct_id: str

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        case = ctx.session.state["patient_case"]
        profile = PatientProfile.model_validate(
            ctx.session.state["patient_profile"]
        )

        trial = trials().get(self.nct_id)
        if trial is None:
            raise RuntimeError(
                f"Retrieved trial {self.nct_id} is missing from trial storage."
            )

        criteria, summary, dropped = await asyncio.to_thread(
            judge, case, profile, trial
        )

        result = {
            "criteria": [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in criteria
            ],
            "summary": summary,
            "dropped_unverified": dropped,
        }

        yield stage_event(
            ctx,
            self.name,
            {f"trial_judgement:{self.nct_id}": result},
        )


class ParallelEligibilityAgent(BaseAgent):
    """Run trial evaluations concurrently in bounded batches."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        candidates = ctx.session.state.get("trial_candidates", [])
        batch_size = max(1, settings.adk_concurrency)

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]

            workers = [
                TrialEligibilityAgent(
                    name=f"trial_judge_{start + offset}",
                    nct_id=item["nct_id"],
                )
                for offset, item in enumerate(batch)
            ]

            parallel = ParallelAgent(
                name=f"parallel_trial_batch_{start // batch_size + 1}",
                description="Evaluate independent clinical trial eligibility.",
                sub_agents=workers,
                timeout=settings.adk_timeout_seconds,
            )

            async for event in parallel.run_async(ctx):
                yield event

        yield stage_event(ctx, self.name)


class FinalRankingAgent(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        profile = PatientProfile.model_validate(state["patient_profile"])
        candidate_records = state.get("trial_candidates", [])
        all_trials = trials()
        all_chunks = chunks()

        evaluated = []

        for candidate in candidate_records:
            nct_id = candidate["nct_id"]
            raw = state.get(f"trial_judgement:{nct_id}")

            # Never infer eligibility if evaluation did not produce a result.
            if raw is None:
                continue

            criteria = [
                CriterionResult.model_validate(item)
                for item in raw["criteria"]
            ]
            verdict = compute_verdict(criteria)

            evaluated.append(
                (candidate, all_trials[nct_id], criteria, raw, verdict)
            )

        evaluated.sort(
            key=lambda item: (
                VERDICT_ORDER.get(item[4], 1),
                -item[0]["rrf"],
            )
        )

        matches = []

        for rank, (candidate, trial, criteria, raw, verdict) in enumerate(
            evaluated[: settings.final_results], start=1
        ):
            passages = [
                Passage(
                    chunk_type=all_chunks[chunk_id]["type"],
                    text=all_chunks[chunk_id]["text"][:700],
                )
                for chunk_id in candidate["chunk_ids"][:3]
                if chunk_id in all_chunks
            ]

            matches.append(
                TrialMatch(
                    rank=rank,
                    nct_id=trial["nct_id"],
                    title=trial["title"],
                    url=f"https://clinicaltrials.gov/study/{trial['nct_id']}",
                    status=trial["status"],
                    phases=trial.get("phases", []),
                    conditions=trial.get("conditions", [])[:6],
                    sponsor=trial.get("sponsor"),
                    locations=trial.get("locations", [])[:3],
                    relevance_score=round(candidate["best_sim"], 3),
                    verdict=verdict,
                    summary=raw["summary"],
                    criteria=criteria,
                    dropped_unverified=raw["dropped_unverified"],
                    passages=passages,
                )
            )

        response = MatchResponse(
            patient_profile=profile,
            matches=matches,
            disclaimer=DISCLAIMER,
            latency_seconds=round(
                time.time() - state["workflow_started_at"], 1
            ),
        )

        yield stage_event(
            ctx,
            self.name,
            {"match_response": response.model_dump(mode="json")},
        )


def build_workflow() -> SequentialAgent:
    """Build the request-independent ADK workflow."""
    return SequentialAgent(
        name="clinical_trial_matching_workflow",
        description=(
            "Parse a patient case, retrieve clinical trials, evaluate "
            "eligibility in parallel, and rank the results."
        ),
        sub_agents=[
            PatientParserAgent(name="patient_parser"),
            TrialRetrievalAgent(name="trial_retriever"),
            ParallelEligibilityAgent(name="eligibility_orchestrator"),
            FinalRankingAgent(name="final_ranker"),
        ],
        timeout=settings.adk_timeout_seconds,
    )


async def _run_workflow_async(patient_case: str) -> MatchResponse:
    app_name = settings.adk_app_name
    user_id = "clinical-trial-api"
    session_id = str(uuid.uuid4())

    # Request-scoped session service prevents cases from sharing session state.
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state={
            "patient_case": patient_case,
            "workflow_started_at": time.time(),
        },
    )

    runner = Runner(
        app_name=app_name,
        agent=build_workflow(),
        session_service=session_service,
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text="Run the clinical trial matching workflow.")],
    )

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        pass

    session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

    if session is None:
        raise RuntimeError("ADK workflow session was not found.")

    result = session.state.get("match_response")
    if result is None:
        raise RuntimeError("ADK workflow completed without a match response.")

    return MatchResponse.model_validate(result)


def run_adk_workflow(patient_case: str) -> MatchResponse:
    """Synchronous entry point for the existing synchronous FastAPI route."""
    return asyncio.run(_run_workflow_async(patient_case))
