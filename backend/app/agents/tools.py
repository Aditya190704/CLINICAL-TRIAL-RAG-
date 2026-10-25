"""Approved, bounded wrappers around existing application services."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.schemas import PatientProfile
from app.services.retriever import Candidate, retrieve
from app.services.safety import safe_search_query

MAX_RETRIEVAL_CALLS = 2


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)


class ApprovedTrialRetrieval:
    """Request-local retrieval capability with profile and call-count checks."""

    def __init__(self, *, case: str, profile: PatientProfile):
        self._case = case
        self._profile = profile
        self.calls = 0

    async def search(self, query: str | list[str]) -> list[Candidate]:
        if self.calls >= MAX_RETRIEVAL_CALLS:
            raise ValueError("The request retrieval limit has been reached.")

        proposed_queries = [query] if isinstance(query, str) else query
        if not isinstance(proposed_queries, list):
            raise ValueError("Retrieval queries must be text values.")

        safe_queries = list(dict.fromkeys(
            safe_search_query(
                RetrievalQuery(query=item).query,
                self._case,
                self._profile,
            )
            for item in proposed_queries
        ))
        if not safe_queries:
            raise ValueError("At least one grounded retrieval query is required.")

        self.calls += 1
        return await asyncio.wait_for(
            asyncio.to_thread(retrieve, safe_queries),
            timeout=min(60.0, settings.adk_timeout_seconds),
        )

