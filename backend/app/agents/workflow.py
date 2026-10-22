"""Bounded ADK reasoning inside a deterministic clinical-trial workflow."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from typing import Any

from app.agents.tasks import assess_trial, extract_patient
from app.agents.tools import ApprovedTrialRetrieval
from app.config import settings
from app.safe_logging import error_status_code, log_safe_error
from app.schemas import CriterionResult, MatchResponse, PatientProfile, TrialMatch
from app.services.eligibility_judge import compute_verdict, verify_judge_output
from app.services.safety import (
    detect_supported_conflicts,
    derive_missing_facts,
    safe_search_query,
    validate_extracted_profile,
)
from app.services.trial_store import chunks, trials
from app.services.untrusted_text import contains_instruction_like_text, remove_instruction_like_clauses

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "This tool provides research assistance, not a medical diagnosis or treatment "
    "recommendation. Trial results are preliminary and do not establish eligibility. "
    "A qualified clinical team must review the official criteria and confirm any decision."
)

MAX_ASSESSMENTS = min(settings.final_results, settings.candidates_to_judge)
MAX_WORKFLOW_SECONDS = min(
    300.0,
    max(60.0, settings.adk_timeout_seconds * (MAX_ASSESSMENTS + 1) + 30.0),
)


class WorkflowError(RuntimeError):
    """Safe, user-facing workflow failure with no provider detail."""

    def __init__(self, code: str, message: str, status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _log_failure(request_id: str, step: str, exc: BaseException) -> None:
    """Compatibility wrapper for the shared sanitized error logger."""
    log_safe_error(logger, request_id=request_id, step=step, error=exc)


def _text(value: Any) -> str:
    if value is None or isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _trial_id(trial: dict[str, Any]) -> str:
    return _text(trial.get("nct_id")).upper()


def _trial_title(trial: dict[str, Any]) -> str:
    return (
        _text(trial.get("brief_title"))
        or _text(trial.get("title"))
        or _text(trial.get("official_title"))
        or _trial_id(trial)
    )


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
    try:
        score = float(_candidate_value(candidate, "best_sim", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return score if math.isfinite(score) and 0 <= score <= 1 else 0.0


def _candidate_chunk_ids(candidate: Any) -> list[str]:
    value = _candidate_value(candidate, "chunk_ids", [])
    return [str(item) for item in value if item is not None] if isinstance(value, (list, tuple)) else []


def _trial_index() -> dict[str, dict[str, Any]]:
    raw = trials()
    if isinstance(raw, dict):
        return {str(key).upper(): value for key, value in raw.items() if isinstance(value, dict)}
    result: dict[str, dict[str, Any]] = {}
    for item in raw or []:
        if isinstance(item, dict) and _trial_id(item):
            result[_trial_id(item)] = item
    return result


def _dedupe_candidates(raw: list[Any], index: dict[str, dict[str, Any]]) -> list[Any]:
    by_id: dict[str, Any] = {}
    for candidate in raw:
        nct_id = _candidate_id(candidate)
        if not re.fullmatch(r"NCT\d{8}", nct_id) or nct_id not in index:
            continue
        if bool(_candidate_value(candidate, "untrusted_instruction", False)):
            continue
        trial = index[nct_id]
        if any(contains_instruction_like_text(_text(trial.get(field))) for field in ("title", "brief_title", "official_title", "eligibility_text")):
            continue
        prior = by_id.get(nct_id)
        if prior is None or _candidate_score(candidate) > _candidate_score(prior):
            by_id[nct_id] = candidate
    return sorted(by_id.values(), key=lambda item: (-_candidate_score(item), _candidate_id(item)))


def _merge_candidates(first: list[Any], second: list[Any], index: dict[str, dict[str, Any]]) -> list[Any]:
    return _dedupe_candidates(first + second, index)


def _get_passages(candidate: Any, nct_id: str, max_passages: int = 3) -> list[dict[str, str]]:
    raw = chunks()
    if isinstance(raw, dict):
        lookup = raw
    else:
        lookup = {
            _text(item.get("chunk_id")): item
            for item in raw or []
            if isinstance(item, dict) and _text(item.get("chunk_id"))
        }
    passages: list[dict[str, str]] = []
    for chunk_id in _candidate_chunk_ids(candidate):
        item = lookup.get(chunk_id)
        if not item or _text(item.get("nct_id")).upper() != nct_id:
            continue
        text = _text(item.get("chunk_text") or item.get("text") or item.get("content"))
        if text:
            passages.append({
                "chunk_type": _text(item.get("chunk_type") or item.get("section")) or "Trial information",
                "text": text[:700],
            })
        if len(passages) >= max_passages:
            break
    return passages


def _verdict_priority(verdict: str) -> int:
    return {"ELIGIBLE": 0, "POSSIBLY_ELIGIBLE": 1, "EXCLUDED": 2}.get(verdict, 3)


def _criterion_priority(criteria: list[CriterionResult]) -> tuple[int, int, int]:
    supports = sum(item.impact == "SUPPORTS" for item in criteria)
    unknowns = sum(item.impact == "UNKNOWN" for item in criteria)
    blocks = sum(item.impact == "BLOCKS" for item in criteria)
    # More missing evidence can never improve a candidate's position.
    return (-supports, unknowns, blocks)


def _build_match(candidate: Any, trial: dict[str, Any], assessment: dict[str, Any], rank: int) -> TrialMatch:
    nct_id = _trial_id(trial)
    return TrialMatch(
        rank=rank,
        nct_id=nct_id,
        title=_trial_title(trial),
        url=_trial_url(nct_id),
        status=_text(trial.get("overall_status") or trial.get("status")) or "Unknown",
        phases=trial.get("phases") or [],
        conditions=(trial.get("conditions") or [])[:6],
        sponsor=_text(trial.get("lead_sponsor") or trial.get("sponsor")) or None,
        locations=(trial.get("locations") or [])[:3],
        relevance_score=round(_candidate_score(candidate), 3),
        verdict=assessment["verdict"],
        summary=assessment["summary"],
        criteria=assessment["criteria"],
        dropped_unverified=assessment["dropped_unverified"],
        passages=_get_passages(candidate, nct_id),
    )


async def _run_steps(case: str, request_id: str) -> MatchResponse:
    # Make a normal and injection-appended case identical before extraction,
    # conflict checks, retrieval, and evidence verification.
    case = remove_instruction_like_clauses(case)
    try:
        extracted = await extract_patient(case)
        profile = validate_extracted_profile(extracted.profile, case)
    except Exception as exc:
        _log_failure(request_id, "extraction", exc)
        status_code = error_status_code(exc)
        raise WorkflowError(
            "PATIENT_PARSE_FAILED",
            "We could not extract a reliable patient profile. Review the case and try again.",
            status_code=503 if status_code == 429 else 504 if status_code == 408 else 500,
        ) from exc

    conflicts, excluded_values = detect_supported_conflicts(case)
    missing = derive_missing_facts(profile)
    conflicts = list(dict.fromkeys(conflicts))

    try:
        query = safe_search_query(profile.search_query, case, profile)
        for value in excluded_values:
            query = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", " ", query, flags=re.I)
        query = " ".join(query.split())
        query = safe_search_query(query, case, profile)
        retrieval = ApprovedTrialRetrieval(case=case, profile=profile)
        first_raw = await retrieval.search(query)
        index = _trial_index()
        candidates = _dedupe_candidates(first_raw, index)
    except Exception as exc:
        _log_failure(request_id, "initial_retrieval", exc)
        raise WorkflowError(
            "TRIAL_RETRIEVAL_FAILED",
            "We could not search clinical trials right now. Please try again later.",
            status_code=(
                503 if isinstance(exc, PermissionError) or error_status_code(exc) == 429
                else 504 if isinstance(exc, (asyncio.TimeoutError, TimeoutError))
                else 500
            ),
        ) from exc

    retrieval_calls = retrieval.calls
    if not candidates:
        logger.info("request_id=%s step=matching_complete candidates=0 retrieval_calls=%d", request_id, retrieval_calls)
        return MatchResponse(
            patient_profile=profile,
            matches=[],
            disclaimer=DISCLAIMER,
            missing_key_facts=missing,
            conflicting_facts=conflicts,
        )

    assessment_cap = max(0, min(int(settings.candidates_to_judge), int(settings.final_results)))
    candidates = candidates[:assessment_cap]
    try:
        assessments: dict[str, dict[str, Any]] = {}
        # Assess serially so a provider error halts the request before later
        # trial assessment calls are sent.
        for candidate in candidates:
            nct_id = _candidate_id(candidate)
            output = await assess_trial(case=case, profile=profile, trial=index[nct_id])
            criteria, _, dropped = verify_judge_output(case, profile, index[nct_id], output)
            verdict = compute_verdict(criteria)
            summary = (
                "A potentially disqualifying criterion was identified in this preliminary review. A qualified clinical team must verify it."
                if verdict == "EXCLUDED"
                else "The available criteria do not establish eligibility. Some information may be missing or unassessed; a qualified clinical team must review the official criteria."
            )
            assessments[nct_id] = {
                "criteria": criteria,
                "summary": summary,
                "dropped_unverified": dropped,
                "verdict": verdict,
            }
    except Exception as exc:
        _log_failure(request_id, "criteria_assessment", exc)
        status_code = error_status_code(exc)
        raise WorkflowError(
            "JUDGEMENT_PIPELINE_FAILED",
            "We could not complete trial criteria assessment. Please try again later.",
            status_code=503 if status_code == 429 else 504 if status_code == 408 else 500,
        ) from exc

    ranked = sorted(candidates, key=lambda candidate: (-_candidate_score(candidate), _candidate_id(candidate)))
    matches = [
        _build_match(candidate, index[_candidate_id(candidate)], assessments[_candidate_id(candidate)], rank)
        for rank, candidate in enumerate(ranked[:max(0, int(settings.final_results))], start=1)
    ]
    logger.info(
        "request_id=%s step=matching_complete candidates=%d results=%d retrieval_calls=%d",
        request_id,
        len(candidates),
        len(matches),
        retrieval_calls,
    )
    return MatchResponse(
        patient_profile=profile,
        matches=matches,
        disclaimer=DISCLAIMER,
        missing_key_facts=missing,
        conflicting_facts=conflicts,
    )


async def run_workflow_async(case: str, request_id: str | None = None) -> MatchResponse:
    """Async workflow entry point, independent of FastAPI request objects."""
    request_id = request_id or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        return await asyncio.wait_for(_run_steps(case, request_id), timeout=MAX_WORKFLOW_SECONDS)
    except asyncio.TimeoutError as exc:
        _log_failure(request_id, "workflow_timeout", exc)
        raise WorkflowError(
            "WORKFLOW_TIMEOUT",
            "Trial matching took too long to complete. Please try again.",
            status_code=504,
        ) from exc
    finally:
        logger.info("request_id=%s step=workflow_finished duration_ms=%d", request_id, int((time.perf_counter() - started) * 1000))


def run_adk_workflow(case: str, request_id: str | None = None) -> MatchResponse:
    """Sync adapter for CLI and sync callers; refuses nested event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_workflow_async(case, request_id=request_id))
    raise RuntimeError("An event loop is already running; await run_workflow_async instead.")
