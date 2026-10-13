
# backend/app/services/pipeline.py

import re

from app.schemas import MatchResponse
from app.agents.workflow import run_adk_workflow

# Keep these imports for compatibility with existing tests.
from app.services.trial_store import chunks, trials

PHI = re.compile(
    r"(\b\d{3}-\d{2}-\d{4}\b|"
    r"[\w.+-]+@[\w-]+\.[\w.-]+|"
    r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b)"
)

ORDER = {
    "ELIGIBLE": 0,
    "POSSIBLY_ELIGIBLE": 1,
    "EXCLUDED": 2,
}


def run(case: str) -> MatchResponse:
    if PHI.search(case):
        raise ValueError(
            "Possible identifiers (SSN / email / phone) detected. "
            "Please anonymise the case."
        )

    return run_adk_workflow(case)
