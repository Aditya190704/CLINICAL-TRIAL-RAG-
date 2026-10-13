"""Lifecycle callbacks and guardrails for Google ADK agents."""
import logging
import re
import time
from typing import Optional

from google.adk.agents.context import Context
from google.adk.events import Event

from app.agents.state import (
    STATE_PATIENT_CASE,
    STATE_PATIENT_PROFILE,
    STATE_CANDIDATES,
    STATE_VERIFIED_EVALUATIONS,
    get_state_value,
)

logger = logging.getLogger("adk.callbacks")

# PHI regex for privacy guardrail: SSN, email, phone numbers
PHI_PATTERN = re.compile(
    r"(\b\d{3}-\d{2}-\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b)"
)


def privacy_guardrail_before_agent(ctx: Context) -> Optional[Event]:
    """Guardrail callback: Validates input privacy before agent execution.

    Rejects any case text containing identifiable personal health information (PHI)
    such as Social Security Numbers, email addresses, or phone numbers.
    """
    case = get_state_value(ctx.state, STATE_PATIENT_CASE, "")
    if not case and ctx.user_content:
        # Extract from user_content parts if state is not yet populated
        case = "".join(p.text for p in getattr(ctx.user_content, "parts", []) if hasattr(p, "text"))

    if case and PHI_PATTERN.search(case):
        logger.warning(
            f"Privacy guardrail triggered: Identifiable PHI detected in session {ctx.session.id}. Aborting."
        )
        raise ValueError(
            "Possible identifiers (SSN / email / phone) detected. Please anonymise the case."
        )
    return None


def observability_before_agent(ctx: Context) -> Optional[Event]:
    """Logs operational metadata before agent execution.

    Never logs patient narrative, credentials, or sensitive health data.
    """
    agent_name = ctx.agent_name or "unknown_agent"
    session_id = ctx.session.id if hasattr(ctx, "session") and ctx.session else "unknown_session"
    logger.info(
        f"[ADK Invocation] Agent '{agent_name}' starting | Session: {session_id} | Invocation: {ctx.invocation_id}"
    )
    # Store start timestamp in custom metadata or telemetry context
    if not hasattr(ctx, "_start_times"):
        ctx._start_times = {}
    ctx._start_times[agent_name] = time.time()
    return None


def observability_after_agent(ctx: Context) -> Optional[Event]:
    """Logs operational duration and counts after agent execution."""
    agent_name = ctx.agent_name or "unknown_agent"
    start_time = getattr(ctx, "_start_times", {}).get(agent_name)
    duration_str = f"{(time.time() - start_time):.2f}s" if start_time else "N/A"

    state_dict = ctx.state.to_dict() if hasattr(ctx.state, "to_dict") else {}
    cands = state_dict.get(STATE_CANDIDATES, [])
    evals = state_dict.get(STATE_VERIFIED_EVALUATIONS, [])

    logger.info(
        f"[ADK Invocation] Agent '{agent_name}' completed | Duration: {duration_str} | "
        f"Candidates: {len(cands) if isinstance(cands, list) else 0} | "
        f"Verified Matches: {len(evals) if isinstance(evals, list) else 0}"
    )
    return None


def age_validation_after_parser(ctx: Context) -> Optional[Event]:
    """Validates extracted patient age against original narrative.

    An extracted age must literally appear in the source text to prevent
    hallucinatory age inference by language models.
    """
    case = get_state_value(ctx.state, STATE_PATIENT_CASE, "")
    profile_dict = get_state_value(ctx.state, STATE_PATIENT_PROFILE)

    if profile_dict and isinstance(profile_dict, dict):
        age_years = profile_dict.get("age_years")
        if age_years is not None:
            try:
                age_int = int(age_years)
                if not re.search(rf"\b{age_int}\b", case):
                    logger.info(
                        f"Parser guardrail: Age {age_years} not found verbatim in narrative. Setting to None."
                    )
                    profile_dict["age_years"] = None
                    ctx.state.update({STATE_PATIENT_PROFILE: profile_dict})
            except Exception as e:
                logger.debug(f"Age verification check exception: {e}")
    return None

