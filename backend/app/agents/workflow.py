"""Bounded ADK reasoning inside a deterministic clinical-trial workflow."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from typing import Any

from app.agents.tasks import assess_trial, extract_patient, propose_refinement
from app.agents.tools import ApprovedTrialRetrieval
from app.config import settings
from app.safe_logging import error_status_code, log_safe_error
from app.schemas import CriterionResult, MatchResponse, PatientProfile, RuledOutTrial, TrialMatch
from app.services.eligibility_judge import compute_verdict, verify_judge_output
from app.services.safety import (
    detect_supported_conflicts,
    derive_missing_facts,
    remove_conflicting_fact_mentions,
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

HARD_MAX_ASSESSMENTS = 10
MAX_ASSESSMENTS = min(HARD_MAX_ASSESSMENTS, settings.candidates_to_judge)
MAX_SHORTLIST_RESULTS = 3
REFINEMENT_MIN_SIMILARITY = 0.35
MAX_WORKFLOW_SECONDS = min(
    300.0,
    max(60.0, settings.adk_timeout_seconds * (MAX_ASSESSMENTS + 2) + 30.0),
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


def _string_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return []
    return [item.strip() for item in values if isinstance(item, str) and item.strip()][:limit]


def _trial_index() -> dict[str, dict[str, Any]]:
    raw = trials()
    if isinstance(raw, dict):
        result = {}
        for key, value in raw.items():
            nct_id = str(key).strip().upper()
            if not re.fullmatch(r"NCT\d{8}", nct_id) or not isinstance(value, dict):
                continue
            record = dict(value)
            record_id = _trial_id(record)
            if record_id and record_id != nct_id:
                continue
            if not record_id:
                record["nct_id"] = nct_id
            result[nct_id] = record
        return result
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


def _chunk_index() -> dict[str, Any]:
    raw = chunks()
    if isinstance(raw, dict):
        return raw
    return {
        _text(item.get("chunk_id")): item
        for item in raw or []
        if isinstance(item, dict) and _text(item.get("chunk_id"))
    }


def _get_passages(
    candidate: Any,
    nct_id: str,
    lookup: dict[str, Any] | None = None,
    max_passages: int = 3,
) -> list[dict[str, str]]:
    lookup = lookup if lookup is not None else _chunk_index()
    passages: list[dict[str, str]] = []
    for chunk_id in _candidate_chunk_ids(candidate):
        item = lookup.get(chunk_id)
        if not isinstance(item, dict) or _text(item.get("nct_id")).upper() != nct_id:
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
    return {
        "ELIGIBLE": 0,
        "POSSIBLY_ELIGIBLE": 1,
        "COULD_NOT_ASSESS": 2,
        "EXCLUDED": 3,
    }.get(verdict, 4)


def _criterion_priority(criteria: list[CriterionResult]) -> tuple[int, int, int]:
    supports = sum(item.impact == "SUPPORTS" for item in criteria)
    unknowns = sum(item.impact == "UNKNOWN" for item in criteria)
    blocks = sum(item.impact == "BLOCKS" for item in criteria)
    # More missing evidence can never improve a candidate's position.
    return (-supports, unknowns, blocks)


def _unresolved_count(criteria: list[CriterionResult]) -> int:
    return sum(item.impact == "UNKNOWN" for item in criteria)


def _refinement_query_is_useful(query: str, initial_query: str) -> bool:
    initial_terms = set(re.findall(r"[a-z0-9]+", initial_query.casefold()))
    refined_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    return bool(refined_terms - initial_terms)


def _refinement_query_is_profile_grounded(query: str, profile: PatientProfile) -> bool:
    supported_values = [
        profile.search_query,
        *profile.primary_conditions,
        *profile.comorbidities,
        *profile.current_medications,
        *profile.prior_treatments,
        *profile.key_findings,
    ]
    supported_terms = {
        term
        for value in supported_values
        for term in re.findall(r"[a-z0-9]+", str(value).casefold())
    }
    query_terms = re.findall(r"[a-z0-9]+", query.casefold())
    return bool(query_terms) and all(term in supported_terms for term in query_terms)


def _build_match(
    candidate: Any,
    trial: dict[str, Any],
    assessment: dict[str, Any],
    rank: int,
    chunk_lookup: dict[str, Any],
) -> TrialMatch:
    nct_id = _trial_id(trial)
    return TrialMatch(
        rank=rank,
        nct_id=nct_id,
        title=_trial_title(trial),
        url=_trial_url(nct_id),
        status=_text(trial.get("overall_status") or trial.get("status")) or "Unknown",
        phases=_string_list(trial.get("phases"), 20),
        conditions=_string_list(trial.get("conditions"), 6),
        sponsor=_text(trial.get("lead_sponsor") or trial.get("sponsor")) or None,
        locations=_string_list(trial.get("locations"), 3),
        relevance_score=round(_candidate_score(candidate), 3),
        verdict=assessment["verdict"],
        summary=assessment["summary"],
        criteria=assessment["criteria"],
        dropped_unverified=assessment["dropped_unverified"],
        passages=_get_passages(candidate, nct_id, chunk_lookup),
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
    assessment_case = remove_conflicting_fact_mentions(case, excluded_values)

    try:
        # Search both the core diagnosis and the richer validated profile so
        # subtype, stage, biomarkers, and treatment facts can improve ranking.
        condition_query = " ".join(profile.primary_conditions) or profile.search_query
        detailed_query = profile.search_query or condition_query
        grounded_queries = []
        for proposed_query in (condition_query, detailed_query):
            safe_query = safe_search_query(proposed_query, case, profile)
            for value in excluded_values:
                safe_query = re.sub(
                    rf"(?<!\w){re.escape(value)}(?!\w)",
                    " ",
                    safe_query,
                    flags=re.I,
                )
            safe_query = " ".join(safe_query.split())
            if safe_query:
                grounded_queries.append(safe_search_query(safe_query, case, profile))
        grounded_queries = list(dict.fromkeys(grounded_queries))
        query = grounded_queries[-1] if grounded_queries else safe_search_query(
            profile.search_query,
            case,
            profile,
        )
        retrieval = ApprovedTrialRetrieval(case=case, profile=profile)
        first_raw = await retrieval.search(grounded_queries or [query])
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
            result_message="No suitable trial was found in this search. This does not mean that no suitable trial exists.",
        )

    try:
        # Criteria checks are independent model calls. Bound their concurrency
        # to avoid serial latency while respecting the configured provider cap.
        assessment_limit = max(1, int(settings.adk_concurrency))
        semaphore = asyncio.Semaphore(assessment_limit)
        assessment_cap = max(0, min(HARD_MAX_ASSESSMENTS, int(settings.candidates_to_judge)))

        async def assess_candidate(candidate: Any) -> tuple[str, dict[str, Any]]:
            nct_id = _candidate_id(candidate)
            trial = index[nct_id]
            async with semaphore:
                output = await assess_trial(case=assessment_case, profile=profile, trial=trial)
            criteria, _, dropped = verify_judge_output(assessment_case, profile, index[nct_id], output)
            verdict = compute_verdict(criteria)
            summary = (
                "A potentially disqualifying criterion was identified in this preliminary review. A qualified clinical team must verify it."
                if verdict == "EXCLUDED"
                else "The available evidence was insufficient to assess this trial's criteria. A qualified clinical team must review the official criteria."
                if verdict == "COULD_NOT_ASSESS"
                else "The available criteria do not establish eligibility. Some information may be missing or unassessed; a qualified clinical team must review the official criteria."
            )
            return nct_id, {
                "criteria": criteria,
                "summary": summary,
                "dropped_unverified": dropped,
                "verdict": verdict,
            }

        async def assess_candidates(items: list[Any]) -> dict[str, dict[str, Any]]:
            assessment_tasks = [asyncio.create_task(assess_candidate(item)) for item in items]
            try:
                return dict(await asyncio.gather(*assessment_tasks))
            except BaseException:
                for task in assessment_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*assessment_tasks, return_exceptions=True)
                raise

        # Weak retrieval refinement used to sit on the critical path before
        # any eligibility work began. Overlap its optional model/search work
        # with assessment of the initial shortlist. Strong results never pay
        # for refinement, and the backend still permits at most two searches.
        initial_candidates = candidates[:assessment_cap]
        should_refine = (
            not candidates
            or _candidate_score(candidates[0]) < REFINEMENT_MIN_SIMILARITY
        )
        refinement_task = None
        if should_refine:
            refinement_task = asyncio.create_task(
                propose_refinement(case=case, profile=profile, candidate_count=len(candidates))
            )

        try:
            assessments = await assess_candidates(initial_candidates)
        except BaseException:
            if refinement_task is not None and not refinement_task.done():
                refinement_task.cancel()
                await asyncio.gather(refinement_task, return_exceptions=True)
            raise

        if refinement_task is not None:
            refined_candidates = None
            try:
                proposal = await refinement_task
                if proposal.refine:
                    refined_query = safe_search_query(proposal.search_query, case, profile)
                    for value in excluded_values:
                        refined_query = re.sub(
                            rf"(?<!\w){re.escape(value)}(?!\w)",
                            " ",
                            refined_query,
                            flags=re.I,
                        )
                    refined_query = " ".join(refined_query.split())
                    if (
                        refined_query
                        and _refinement_query_is_profile_grounded(refined_query, profile)
                        and _refinement_query_is_useful(refined_query, query)
                    ):
                        second_raw = await retrieval.search(refined_query)
                        candidates = _merge_candidates(candidates, second_raw, index)
                        retrieval_calls = retrieval.calls
                        refined_candidates = candidates[:assessment_cap]
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    if refinement_task and not refinement_task.done():
                        refinement_task.cancel()
                    raise
                # Refinement is optional. Preserve valid initial results if the
                # optional agent or second retrieval fails.
                _log_failure(request_id, "optional_refinement", exc)
            if refined_candidates is not None:
                missing_candidates = [
                    item for item in refined_candidates
                    if _candidate_id(item) not in assessments
                ]
                if missing_candidates:
                    assessments.update(await assess_candidates(missing_candidates))
                candidates = refined_candidates
        candidates = candidates[:assessment_cap]
    except Exception as exc:
        _log_failure(request_id, "criteria_assessment", exc)
        status_code = error_status_code(exc)
        raise WorkflowError(
            "JUDGEMENT_PIPELINE_FAILED",
            "We could not complete trial criteria assessment. Please try again later.",
            status_code=503 if status_code == 429 else 504 if status_code == 408 else 500,
        ) from exc

    ranked = sorted(
        candidates,
        key=lambda candidate: (
            _verdict_priority(assessments[_candidate_id(candidate)]["verdict"]),
            _unresolved_count(assessments[_candidate_id(candidate)]["criteria"]),
            -_candidate_score(candidate),
            _candidate_id(candidate),
        ),
    )
    ruled_out = []
    for candidate in ranked:
        nct_id = _candidate_id(candidate)
        assessment = assessments[nct_id]
        if assessment["verdict"] != "EXCLUDED":
            continue
        blocker = next(
            (item for item in assessment["criteria"] if item.impact == "BLOCKS"),
            None,
        )
        if blocker is not None:
            reason = f"Verified blocking criterion: {blocker.criterion_quote}"[:500]
            ruled_out.append(
                RuledOutTrial(
                    nct_id=nct_id,
                    title=_trial_title(index[nct_id]),
                    reason=reason,
                )
            )
    shortlist = [
        candidate
        for candidate in ranked
        if assessments[_candidate_id(candidate)]["verdict"] != "EXCLUDED"
    ][:min(MAX_SHORTLIST_RESULTS, max(0, int(settings.final_results)))]
    chunk_lookup = _chunk_index()
    matches = [
        _build_match(
            candidate,
            index[_candidate_id(candidate)],
            assessments[_candidate_id(candidate)],
            rank,
            chunk_lookup,
        )
        for rank, candidate in enumerate(shortlist, start=1)
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
        ruled_out_trials=ruled_out,
        result_message=(
            "No suitable trial was found in this search. This does not mean that no suitable trial exists."
            if not matches
            else None
        ),
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
