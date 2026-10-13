"""State keys and typed helpers for Google ADK session state."""
from typing import Any

# Standard session state keys
STATE_PATIENT_CASE = "patient_case"
STATE_PATIENT_PROFILE = "patient_profile"
STATE_SEARCH_QUERIES = "search_queries"
STATE_CANDIDATES = "candidates"
STATE_RAW_EVALUATIONS = "raw_evaluations"
STATE_VERIFIED_EVALUATIONS = "verified_evaluations"
STATE_FINAL_RESPONSE = "final_response"
STATE_EXECUTION_METADATA = "execution_metadata"


def get_state_value(state: dict[str, Any] | Any, key: str, default: Any = None) -> Any:
    """Safely get a value from state whether it is a dict or an ADK State object."""
    if hasattr(state, "get"):
        return state.get(key, default)
    if hasattr(state, "to_dict"):
        return state.to_dict().get(key, default)
    return default

