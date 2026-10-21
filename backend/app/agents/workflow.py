
"""ADK workflow for clinical-trial matching.

Pipeline:
1. Parse the patient case.
2. Retrieve relevant trial candidates.
3. Judge eligibility criteria for each candidate.
4. Calculate deterministic verdicts and return the best results.

The retrieval score measures relevance, not clinical eligibility.
"""

from __future__ import annotations #Delays evaluation of type annotations

import asyncio # it supports asyncronous programming, allowing for concurrent execution of tasks
import logging # logging records information about the applications execution, including errors and warnings
from typing import Any # Any is a type hint that allows a value to have different data types

from app.config import settings # this imports settings from your project's config.py file
from app.schemas import (
    CriterionResult,
    MatchResponse,
    PatientProfile,
    TrialMatch,
) # This imports several classes from the app.schemas module, which are used to define the structure of data in the application
from app.services.eligibility_judge import compute_verdict, judge
from app.services.patient_parser import parse_patient
from app.services.retriever import retrieve
from app.services.trial_store import trials

logger = logging.getLogger(__name__) # creates a logger for the current python file so we can record messages, warnings, and errors.

DISCLAIMER = (
    "This tool provides research assistance, not a medical diagnosis or treatment "
    "recommendation. Trial matches are preliminary. A qualified clinical team must "
    "verify the official eligibility criteria and confirm eligibility."
) # this variable stores a medical disclaimer message that informs users that the tool is for research assistance only and does not provide medical advice or recommendations.


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return ""
    return str(value).strip() # this helper function converts a value into a clean string. It returns an emoty string for None, lists, and dictionaries


def _trial_id(trial: dict[str, Any]) -> str:
    return _text(trial.get("nct_id")).upper() # extracts a clinical trial's ID from a dictionary and converts it to uppercase


def _trial_title(trial: dict[str, Any]) -> str: #Gets the best available title for a clinical trial. If one title is missing, it tries another field
    return (
        _text(trial.get("brief_title"))
        or _text(trial.get("title"))
        or _text(trial.get("official_title"))
        or _trial_id(trial)
    ) 

'''The or operator checks values from left to right and returns the first non-empty string.
1. trial.get("brief_title") — tries the short trial title.
2. trial.get("title") — if the first is missing or empty, tries title.
3. trial.get("official_title") — if the previous options are empty, tries the official title.
4. _trial_id(trial) — if no title is available, uses the trial ID as a fallback.
The _text() helper converts missing values into empty strings and cleans whitespace.'''


def _trial_url(nct_id: str) -> str:
    return f"https://clinicaltrials.gov/study/{nct_id}"


def _candidate_id(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return _text(candidate.get("nct_id")).upper()
    return _text(getattr(candidate, "nct_id", "")).upper()


def _candidate_value(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _candidate_score(candidate: Any) -> float:
    """Return a safe relevance score in the range 0..1."""
    value = _candidate_value(candidate, "best_sim", 0.0)

    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0

    if not 0.0 <= score <= 1.0:
        return 0.0

    return score


def _candidate_chunk_ids(candidate: Any) -> list[str]:
    value = _candidate_value(candidate, "chunk_ids", [])

    if not isinstance(value, (list, tuple)):
        return []

    return [str(item) for item in value if item is not None]


def _get_trial_index() -> dict[str, dict[str, Any]]:
    """Index processed trial metadata by NCT ID."""
    index: dict[str, dict[str, Any]] = {}

    for trial in trials() or []:
        if not isinstance(trial, dict):
            continue

        nct_id = _trial_id(trial)
        if nct_id:
            index[nct_id] = trial

    return index


def _get_passages(
    candidate: Any,
    nct_id: str,
    max_passages: int = 3,
) -> list[dict[str, str]]:
    """Get supporting passages from the local processed chunk store."""
    from app.services.trial_store import chunks

    chunk_index: dict[str, dict[str, Any]] = {}

    for chunk in chunks() or []:
        if not isinstance(chunk, dict):
            continue

        chunk_id = _text(chunk.get("chunk_id"))
        if chunk_id:
            chunk_index[chunk_id] = chunk

    passages: list[dict[str, str]] = []

    for chunk_id in _candidate_chunk_ids(candidate):
        chunk = chunk_index.get(chunk_id)
        if not chunk:
            continue

        chunk_nct = _text(chunk.get("nct_id")).upper()

        # Never attach another trial's text to this candidate.
        if chunk_nct != nct_id:
            continue

        text = (
            _text(chunk.get("chunk_text"))
            or _text(chunk.get("text"))
            or _text(chunk.get("content"))
        )
        if not text:
            continue

        passages.append(
            {
                "chunk_type": (
                    _text(chunk.get("chunk_type"))
                    or _text(chunk.get("section"))
                    or "Trial information"
                ),
                "text": text[:700],
            }
        )

        if len(passages) >= max_passages:
            break

    return passages


async def _judge_one(
    case: str,
    profile: PatientProfile,
    trial: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Judge a single trial without blocking the event loop."""
    async with semaphore:
        nct_id = _trial_id(trial)

        try:
            criteria, summary, dropped_unverified = await asyncio.to_thread(
                judge,
                case,
                profile,
                trial,
            )

            verdict = compute_verdict(criteria)

            return {
                "nct_id": nct_id,
                "criteria": criteria,
                "summary": summary,
                "dropped_unverified": dropped_unverified,
                "verdict": verdict,
                "error": None,
            }

        except Exception as exc:
            logger.warning(
                "Trial judging failed for %s (%s).",
                nct_id or "unknown trial",
                type(exc).__name__,
            )

            # Fail closed: errors must not imply eligibility.
            fallback_criterion = CriterionResult(
                source="STRUCTURED",
                criterion_type="INCLUSION",
                criterion_quote="Eligibility assessment unavailable",
                patient_evidence=None,
                impact="UNKNOWN",
                explanation=(
                    "The automated assessment failed. Eligibility remains "
                    "unverified and requires manual review."
                ),
            )

            return {
                "nct_id": nct_id,
                "criteria": [fallback_criterion],
                "summary": (
                    "The eligibility assessment failed; no positive eligibility "
                    "conclusion can be established."
                ),
                "dropped_unverified": 0,
                "verdict": "POSSIBLY_ELIGIBLE",
                "error": type(exc).__name__,
            }


def _verdict_priority(verdict: str) -> int:
    """Order potentially suitable trials ahead of excluded trials."""
    return {
        "ELIGIBLE": 0,
        "POSSIBLY_ELIGIBLE": 1,
        "EXCLUDED": 2,
    }.get(verdict, 3)


def _criterion_priority(criteria: list[CriterionResult]) -> tuple[int, int, int]:
    """Provide a transparent, deterministic criterion summary for tie-breaking."""
    supports = sum(item.impact == "SUPPORTS" for item in criteria)
    unknowns = sum(item.impact == "UNKNOWN" for item in criteria)
    blocks = sum(item.impact == "BLOCKS" for item in criteria)

    # More supporting evidence first, then fewer unknowns and fewer conflicts.
    return (-supports, unknowns, blocks)


def _build_trial_match(
    candidate: Any,
    trial: dict[str, Any],
    judgement: dict[str, Any],
    rank: int,
) -> TrialMatch:
    nct_id = _trial_id(trial)
    criteria = judgement["criteria"]

    return TrialMatch(
        rank=rank,
        nct_id=nct_id,
        title=_trial_title(trial),
        url=_trial_url(nct_id),
        status=_text(trial.get("overall_status") or trial.get("status"))
        or "Unknown",
        phases=trial.get("phases") or [],
        conditions=(trial.get("conditions") or [])[:6],
        sponsor=_text(trial.get("lead_sponsor") or trial.get("sponsor"))
        or None,
        locations=(trial.get("locations") or [])[:3],
        relevance_score=round(_candidate_score(candidate), 3),
        verdict=judgement["verdict"],
        summary=judgement["summary"],
        criteria=criteria,
        dropped_unverified=int(judgement["dropped_unverified"]),
        passages=_get_passages(candidate, nct_id),
    )


async def _run_workflow_async(case: str) -> MatchResponse:
    """Execute the matching pipeline asynchronously."""
    case = (case or "").strip()

    if len(case) < 40:
        raise ValueError("Patient case must contain at least 40 characters.")

    if len(case) > 8000:
        raise ValueError("Patient case must not exceed 8000 characters.")

    # Stage 1: Parse the patient's explicitly stated facts.
    profile = await asyncio.to_thread(parse_patient, case)

    if not isinstance(profile, PatientProfile):
        profile = PatientProfile.model_validate(profile)

    # Stage 2: Retrieve relevant candidates.
    raw_candidates = await asyncio.to_thread(
        retrieve,
        [profile.search_query, case[:2000]],
    )

    if not raw_candidates:
        return MatchResponse(
            patient_profile=profile,
            matches=[],
            disclaimer=DISCLAIMER,
            latency_seconds=0.0,
        )

    trial_index = _get_trial_index()

    # Deduplicate candidates and discard IDs not found in processed trial data.
    candidates_by_id: dict[str, Any] = {}

    for candidate in raw_candidates:
        nct_id = _candidate_id(candidate)

        if not nct_id or nct_id not in trial_index:
            continue

        previous = candidates_by_id.get(nct_id)
        if previous is None or _candidate_score(candidate) > _candidate_score(previous):
            candidates_by_id[nct_id] = candidate

    candidates = sorted(
        candidates_by_id.values(),
        key=_candidate_score,
        reverse=True,
    )[: settings.candidates_to_judge]

    if not candidates:
        return MatchResponse(
            patient_profile=profile,
            matches=[],
            disclaimer=DISCLAIMER,
            latency_seconds=0.0,
        )

    # Stage 3: Judge candidates in parallel, with bounded concurrency.
    concurrency = max(1, int(settings.adk_concurrency))
    semaphore = asyncio.Semaphore(concurrency)

    judgement_results = await asyncio.gather(
        *[
            _judge_one(
                case=case,
                profile=profile,
                trial=trial_index[_candidate_id(candidate)],
                semaphore=semaphore,
            )
            for candidate in candidates
        ]
    )

    judgement_by_id = {
        item["nct_id"]: item
        for item in judgement_results
    }

    # Stage 4: Rank by deterministic eligibility verdict first.
    # Retrieval similarity breaks ties within the same verdict category.
    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: (
            _verdict_priority(
                judgement_by_id[_candidate_id(candidate)]["verdict"]
            ),
            _criterion_priority(
                judgement_by_id[_candidate_id(candidate)]["criteria"]
            ),
            -_candidate_score(candidate),
        ),
    )

    final_matches: list[TrialMatch] = []

    for rank, candidate in enumerate(
        ranked_candidates[: settings.final_results],
        start=1,
    ):
        nct_id = _candidate_id(candidate)
        final_matches.append(
            _build_trial_match(
                candidate=candidate,
                trial=trial_index[nct_id],
                judgement=judgement_by_id[nct_id],
                rank=rank,
            )
        )

    return MatchResponse(
        patient_profile=profile,
        matches=final_matches,
        disclaimer=DISCLAIMER,
        latency_seconds=0.0,
    )


def run_adk_workflow(case: str) -> MatchResponse:
    """Compatibility entry point used by the existing API pipeline."""
    try:
        return asyncio.run(_run_workflow_async(case))
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" in str(exc):
            raise RuntimeError(
                "run_adk_workflow() cannot be called inside an active event loop. "
                "Use _run_workflow_async() from asynchronous code."
            ) from exc
        raise
