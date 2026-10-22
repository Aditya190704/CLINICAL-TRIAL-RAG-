"""Clinical-trial matching workflow.

Pipeline:
1. Parse the patient case.
2. Retrieve relevant trial candidates.
3. Check eligibility evidence for each candidate.
4. Rank candidates and return the best matches.

The retrieval score measures relevance, not clinical eligibility.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas import CriterionResult, MatchResponse, PatientProfile, TrialMatch
from app.services.eligibility_judge import compute_verdict, judge
from app.services.patient_parser import parse_patient
from app.services.retriever import retrieve
from app.services.trial_store import chunks, trials

logger = logging.getLogger(__name__)
_JUDGE_SEMAPHORE = threading.BoundedSemaphore(
    max(1, int(settings.adk_concurrency))
)

DISCLAIMER = (
    "This tool provides research assistance, not a medical diagnosis or treatment "
    "recommendation. Trial matches are preliminary. A qualified clinical team must "
    "verify the official eligibility criteria and confirm eligibility."
)

# Keep the CSV outside source files. Do not log patient case text or other health details.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _PROJECT_ROOT / "logs"
_ERROR_CSV = _LOG_DIR / "important_errors.csv"
_CSV_LOCK = threading.Lock()
_CSV_FIELDS = [
    "timestamp_utc",
    "level",
    "error_code",
    "stage",
    "trial_id",
    "exception_type",
    "user_message",
    "technical_details",
]


class WorkflowError(RuntimeError):
    """An error with a safe message that can be shown to the user."""

    def __init__(self, error_code: str, user_message: str):
        super().__init__(user_message)
        self.error_code = error_code
        self.user_message = user_message


def _record_important_error(
    *,
    error_code: str,
    stage: str,
    user_message: str,
    exc: BaseException | None = None,
    trial_id: str = "",
    level: str = "ERROR",
) -> None:
    """Write important errors to normal logs and a CSV audit file."""
    exception_type = type(exc).__name__ if exc else ""
    # Keep technical details useful, but never include the patient's case.
    technical_details = str(exc).replace("\n", " ").replace("\r", " ")[:1000] if exc else ""

    logger_method = logger.error if level == "ERROR" else logger.warning
    logger_method(
        "error_code=%s stage=%s trial_id=%s exception_type=%s details=%s",
        error_code,
        stage,
        trial_id or "-",
        exception_type or "-",
        technical_details or "-",
        exc_info=(type(exc), exc, exc.__traceback__) if exc else False,
    )

    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "error_code": error_code,
        "stage": stage,
        "trial_id": trial_id,
        "exception_type": exception_type,
        "user_message": user_message,
        "technical_details": technical_details,
    }

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _CSV_LOCK:
            file_exists = _ERROR_CSV.exists() and _ERROR_CSV.stat().st_size > 0
            with _ERROR_CSV.open("a", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=_CSV_FIELDS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
    except OSError:
        # CSV logging must not hide the original workflow error.
        logger.exception("Could not write the error event to %s", _ERROR_CSV)


def _text(value: Any) -> str:
    """Convert simple values to trimmed text; ignore missing or complex values."""
    if value is None or isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _trial_id(trial: dict[str, Any]) -> str:
    return _text(trial.get("nct_id")).upper()


def _trial_title(trial: dict[str, Any]) -> str:
    """Use the best available trial title."""
    return (
        _text(trial.get("brief_title"))
        or _text(trial.get("title"))
        or _text(trial.get("official_title"))
        or _trial_id(trial)
    )


def _trial_url(nct_id: str) -> str:
    return f"https://clinicaltrials.gov/study/{nct_id}"


def _candidate_id(candidate: Any) -> str:
    """Read an NCT ID whether the candidate is a dictionary or an object."""
    if isinstance(candidate, dict):
        return _text(candidate.get("nct_id")).upper()
    return _text(getattr(candidate, "nct_id", "")).upper()


def _candidate_value(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _candidate_score(candidate: Any) -> float:
    """Return a valid relevance score between 0 and 1."""
    try:
        score = float(_candidate_value(candidate, "best_sim", 0.0))
    except (TypeError, ValueError):
        return 0.0

    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        return 0.0
    return score


def _candidate_chunk_ids(candidate: Any) -> list[str]:
    value = _candidate_value(candidate, "chunk_ids", [])
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item is not None]


def _get_trial_index() -> dict[str, dict[str, Any]]:
    """Load processed trial metadata and index it by NCT ID."""
    raw_trials = trials()
    if isinstance(raw_trials, dict):
        return raw_trials
    trial_index: dict[str, dict[str, Any]] = {}
    for trial in raw_trials or []:
        if not isinstance(trial, dict):
            continue
        nct_id = _trial_id(trial)
        if nct_id:
            trial_index[nct_id] = trial
    return trial_index


def _get_passages(
    candidate: Any,
    nct_id: str,
    max_passages: int = 3,
) -> list[dict[str, str]]:
    """Return evidence passages belonging to this exact trial."""
    raw_chunks = chunks()
    if isinstance(raw_chunks, dict):
        chunk_index = raw_chunks
    else:
        chunk_index: dict[str, dict[str, Any]] = {}
        for chunk in raw_chunks or []:
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

        # Do not accidentally show evidence from a different trial.
        if _text(chunk.get("nct_id")).upper() != nct_id:
            continue

        passage_text = (
            _text(chunk.get("chunk_text"))
            or _text(chunk.get("text"))
            or _text(chunk.get("content"))
        )
        if not passage_text:
            continue

        passages.append(
            {
                "chunk_type": (
                    _text(chunk.get("chunk_type"))
                    or _text(chunk.get("section"))
                    or "Trial information"
                ),
                "text": passage_text[:700],
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
    """Assess one trial, limiting concurrent model calls."""
    async with semaphore:
        nct_id = _trial_id(trial)

        try:
            criteria, _, dropped_unverified = await asyncio.to_thread(
                _judge_with_global_limit, case, profile, trial
            )
            verdict = compute_verdict(criteria)
            if verdict == "EXCLUDED":
                summary = (
                    "A potentially disqualifying criterion was identified in this "
                    "preliminary review. A qualified clinical team must verify the "
                    "evidence against the official trial criteria."
                )
            else:
                summary = (
                    "Some assessed criteria may be supported, but this review may "
                    "be incomplete and does not establish eligibility. A qualified "
                    "clinical team must review all official criteria."
                )

            return {
                "nct_id": nct_id,
                "criteria": criteria,
                "summary": summary,
                "dropped_unverified": dropped_unverified,
                "verdict": verdict,
                "error": None,
            }
        except Exception as exc:
            _record_important_error(
                error_code="TRIAL_JUDGEMENT_FAILED",
                stage="eligibility_judgement",
                trial_id=nct_id,
                user_message=(
                    "We could not complete the automated eligibility assessment "
                    "for one trial. That trial needs manual review."
                ),
                exc=exc,
                level="WARNING",
            )

            # Fail closed: an assessment error must never mean "eligible".
            fallback_criterion = CriterionResult(
                source="STRUCTURED",
                criterion_type="INCLUSION",
                criterion_quote="Eligibility assessment unavailable",
                patient_evidence=None,
                impact="UNKNOWN",
                explanation=(
                    "We couldn't verify this trial's eligibility automatically. "
                    "Do not treat this as a match yet. Review the official trial "
                    "criteria or ask the clinical team to check it manually."
                ),
            )
            return {
                "nct_id": nct_id,
                "criteria": [fallback_criterion],
                "summary": (
                    "We couldn't verify this trial's eligibility automatically. "
                    "Do not treat this as a confirmed match. Ask the clinical team "
                    "to review the official eligibility criteria."
                ),
                "dropped_unverified": 0,
                "verdict": "POSSIBLY_ELIGIBLE",
                "error": type(exc).__name__,
            }


def _judge_with_global_limit(
    case: str,
    profile: PatientProfile,
    trial: dict[str, Any],
) -> tuple[list[CriterionResult], str, int]:
    """Limit judge model calls across concurrent API requests in this process."""
    with _JUDGE_SEMAPHORE:
        return judge(case, profile, trial)


def _verdict_priority(verdict: str) -> int:
    """Rank potential matches before excluded trials."""
    return {"ELIGIBLE": 0, "POSSIBLY_ELIGIBLE": 1, "EXCLUDED": 2}.get(verdict, 3)


def _criterion_priority(criteria: list[CriterionResult]) -> tuple[int, int, int]:
    """Use evidence counts for deterministic tie-breaking."""
    supports = sum(item.impact == "SUPPORTS" for item in criteria)
    unknowns = sum(item.impact == "UNKNOWN" for item in criteria)
    blocks = sum(item.impact == "BLOCKS" for item in criteria)
    return (-supports, unknowns, blocks)


def _build_trial_match(
    candidate: Any,
    trial: dict[str, Any],
    judgement: dict[str, Any],
    rank: int,
) -> TrialMatch:
    """Convert one assessed candidate into the API response schema."""
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
        verdict=judgement["verdict"],
        summary=judgement["summary"],
        criteria=judgement["criteria"],
        dropped_unverified=int(judgement["dropped_unverified"]),
        passages=_get_passages(candidate, nct_id),
    )


async def _run_workflow_async(case: str) -> MatchResponse:
    """Run the full matching pipeline and translate failures into safe messages."""
    case = (case or "").strip()

    # Validate input before calling paid or remote services.
    if len(case) < 40:
        raise ValueError(
            "Please provide a more detailed patient case (at least 40 characters)."
        )
    if len(case) > 8000:
        raise ValueError(
            "The patient case is too long. Please keep it within 8,000 characters."
        )

    # Stage 1: Extract only facts stated in the patient case.
    try:
        profile = await asyncio.to_thread(parse_patient, case)
        if not isinstance(profile, PatientProfile):
            profile = PatientProfile.model_validate(profile)
        if not _text(profile.search_query):
            raise ValueError("The patient parser returned an empty search query.")
    except Exception as exc:
        _record_important_error(
            error_code="PATIENT_PARSE_FAILED",
            stage="patient_parsing",
            user_message=(
                "We couldn't understand the patient case. Please review the details "
                "and try again."
            ),
            exc=exc,
        )
        raise WorkflowError(
            "PATIENT_PARSE_FAILED",
            "We couldn't understand the patient case. Check that the case includes the main diagnosis/condition, age (if known), symptoms or medical history, and any relevant treatments. Remove unrelated text and try again.",
        ) from exc

    # Stage 2: Find trials relevant to the patient's case.
    try:
        raw_candidates = await asyncio.to_thread(
            retrieve, [profile.search_query, case[:2000]]
        )
    except Exception as exc:
        _record_important_error(
            error_code="TRIAL_RETRIEVAL_FAILED",
            stage="retrieval",
            user_message=(
                "We couldn't search clinical trials right now. Check your internet connection and try again in a minute. If this keeps happening, contact support and share error code TRIAL_RETRIEVAL_FAILED."
            ),
            exc=exc,
        )
        raise WorkflowError(
            "TRIAL_RETRIEVAL_FAILED",
            "We couldn't search clinical trials right now. Check your internet connection and try again in a minute. If this keeps happening, contact support and share error code TRIAL_RETRIEVAL_FAILED.",
        ) from exc

    if not raw_candidates:
        logger.info("Retrieval completed successfully but found no trial candidates.")
        return MatchResponse(
            patient_profile=profile,
            matches=[],
            disclaimer=DISCLAIMER,
            latency_seconds=0.0,
        )

    # Metadata is needed to verify candidate IDs and display trial details.
    try:
        trial_index = _get_trial_index()
    except Exception as exc:
        _record_important_error(
            error_code="TRIAL_STORE_READ_FAILED",
            stage="trial_store",
            user_message="Trial data could not be loaded. Retry once. If it still fails, contact support and share error code TRIAL_STORE_READ_FAILED.",
            exc=exc,
        )
        raise WorkflowError(
            "TRIAL_STORE_READ_FAILED",
            "Trial data could not be loaded. Retry once. If it still fails, contact support and share error code TRIAL_STORE_READ_FAILED.",
        ) from exc

    # Deduplicate candidates and ignore trials missing from the processed store.
    candidates_by_id: dict[str, Any] = {}
    for candidate in raw_candidates:
        nct_id = _candidate_id(candidate)
        if not nct_id or nct_id not in trial_index:
            continue

        previous = candidates_by_id.get(nct_id)
        if previous is None or _candidate_score(candidate) > _candidate_score(previous):
            candidates_by_id[nct_id] = candidate

    candidates = sorted(
        candidates_by_id.values(), key=_candidate_score, reverse=True
    )[: max(0, int(settings.candidates_to_judge))]

    if not candidates:
        logger.info("No retrieved candidates matched the local processed trial store.")
        return MatchResponse(
            patient_profile=profile,
            matches=[],
            disclaimer=DISCLAIMER,
            latency_seconds=0.0,
        )

    # Stage 3: Judge candidates in parallel, but cap simultaneous requests.
    try:
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
    except Exception as exc:
        _record_important_error(
            error_code="JUDGEMENT_PIPELINE_FAILED",
            stage="eligibility_judgement",
            user_message=(
                "We couldn't finish checking eligibility for the retrieved trials. Wait a moment and retry. If it happens again, contact support and share error code JUDGEMENT_PIPELINE_FAILED."
            ),
            exc=exc,
        )
        raise WorkflowError(
            "JUDGEMENT_PIPELINE_FAILED",
            "We couldn't finish checking eligibility for the retrieved trials. Wait a moment and retry. If it happens again, contact support and share error code JUDGEMENT_PIPELINE_FAILED.",
        ) from exc

    judgement_by_id = {item["nct_id"]: item for item in judgement_results}

    # Stage 4: Eligibility verdict comes first; relevance breaks ties.
    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: (
            _verdict_priority(judgement_by_id[_candidate_id(candidate)]["verdict"]),
            _criterion_priority(judgement_by_id[_candidate_id(candidate)]["criteria"]),
            -_candidate_score(candidate),
        ),
    )

    final_matches: list[TrialMatch] = []
    try:
        for rank, candidate in enumerate(
            ranked_candidates[: max(0, int(settings.final_results))], start=1
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
    except Exception as exc:
        _record_important_error(
            error_code="RESPONSE_BUILD_FAILED",
            stage="response_building",
            user_message="We found trial candidates but couldn't prepare the results. Retry once. If the problem continues, contact support and share error code RESPONSE_BUILD_FAILED.",
            exc=exc,
        )
        raise WorkflowError(
            "RESPONSE_BUILD_FAILED",
            "We found trial candidates but couldn't prepare the results. Retry once. If the problem continues, contact support and share error code RESPONSE_BUILD_FAILED.",
        ) from exc

    return MatchResponse(
        patient_profile=profile,
        matches=final_matches,
        disclaimer=DISCLAIMER,
        latency_seconds=0.0,
    )


def run_adk_workflow(case: str) -> MatchResponse:
    """Synchronous entry point used by the existing API pipeline."""
    try:
        return asyncio.run(_run_workflow_async(case))
    except WorkflowError:
        # The message is already safe for the user; keep the original error code.
        raise
    except ValueError:
        # Input validation errors are already clear and safe to display.
        raise
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" in str(exc):
            raise RuntimeError(
                "This workflow is already running asynchronously. "
                "Call the async workflow entry point instead."
            ) from exc

        _record_important_error(
            error_code="WORKFLOW_RUNTIME_ERROR",
            stage="workflow",
            user_message="Something unexpected happened while matching trials. Retry once. If it happens again, contact support and share error code WORKFLOW_RUNTIME_ERROR.",
            exc=exc,
        )
        raise WorkflowError(
            "WORKFLOW_RUNTIME_ERROR",
            "Something unexpected happened while matching trials. Retry once. If it happens again, contact support and share error code WORKFLOW_RUNTIME_ERROR.",
        ) from exc
    except Exception as exc:
        _record_important_error(
            error_code="UNEXPECTED_WORKFLOW_ERROR",
            stage="workflow",
            user_message="Something unexpected happened while matching trials. Retry once. If it happens again, contact support and share error code WORKFLOW_RUNTIME_ERROR.",
            exc=exc,
        )
        raise WorkflowError(
            "UNEXPECTED_WORKFLOW_ERROR",
            "Something unexpected happened while matching trials. Retry once. If it happens again, contact support and share error code WORKFLOW_RUNTIME_ERROR.",
        ) from exc
