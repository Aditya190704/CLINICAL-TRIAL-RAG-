"""Unit tests for BigQuery Vector Search Retriever."""
import math
from unittest.mock import MagicMock, patch
import pytest
from google.api_core import exceptions as gcp_exceptions

from app.services.retriever import (
    Candidate,
    validate_embeddings,
    build_vector_search_sql,
    execute_vector_search,
    fuse_and_deduplicate,
    retrieve,
    set_bigquery_client,
)


class DummyRow:
    """Mock BigQuery Row."""
    def __init__(self, **kwargs):
        self._data = kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return self._data.get(key, default)


# ---------------------------------------------------------------------------
# 1. Embedding Validation Tests
# ---------------------------------------------------------------------------

def test_validate_embeddings_success():
    """Valid vectors pass validation without error."""
    vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    validate_embeddings(vectors, expected_dim=3)


def test_validate_embeddings_empty():
    """Empty list of vectors raises ValueError."""
    with pytest.raises(ValueError, match="empty vectors"):
        validate_embeddings([], expected_dim=768)


def test_validate_embeddings_dimension_mismatch():
    """Dimension mismatch raises ValueError."""
    vectors = [[0.1] * 767]  # Expected 768
    with pytest.raises(ValueError, match="dimension mismatch"):
        validate_embeddings(vectors, expected_dim=768)


def test_validate_embeddings_nan_inf():
    """NaN or Inf in embeddings raises ValueError."""
    vectors_nan = [[0.1, float("nan"), 0.3]]
    with pytest.raises(ValueError, match="invalid numerical value"):
        validate_embeddings(vectors_nan, expected_dim=3)

    vectors_inf = [[0.1, float("inf"), 0.3]]
    with pytest.raises(ValueError, match="invalid numerical value"):
        validate_embeddings(vectors_inf, expected_dim=3)


# ---------------------------------------------------------------------------
# 2. BigQuery VECTOR_SEARCH Query Construction Tests
# ---------------------------------------------------------------------------

def test_build_vector_search_sql_single_query():
    """Single query builds valid VECTOR_SEARCH SQL with parameterized subquery."""
    sql = build_vector_search_sql(
        project_id="test-proj",
        dataset_id="clinical_trials",
        table_id="trial_chunks",
        num_queries=1,
    )
    assert "VECTOR_SEARCH(" in sql
    assert "TABLE `test-proj.clinical_trials.trial_chunks`" in sql
    assert "SELECT 0 AS query_id, @q0 AS query_vector" in sql
    assert "distance_type => 'COSINE'" in sql
    assert "top_k => @top_k" in sql
    assert "query_column_to_search => 'query_vector'" in sql


def test_build_vector_search_sql_batch_queries():
    """Multiple queries build valid UNION ALL subquery for batch search."""
    sql = build_vector_search_sql(
        project_id="test-proj",
        dataset_id="clinical_trials",
        table_id="trial_chunks",
        num_queries=3,
    )
    assert "SELECT 0 AS query_id, @q0 AS query_vector" in sql
    assert "UNION ALL" in sql
    assert "SELECT 1 AS query_id, @q1 AS query_vector" in sql
    assert "SELECT 2 AS query_id, @q2 AS query_vector" in sql
    assert "ORDER BY query.query_id, distance ASC" in sql


def test_build_vector_search_sql_invalid_num_queries():
    """0 or negative queries raise ValueError."""
    with pytest.raises(ValueError):
        build_vector_search_sql("proj", "ds", "tbl", num_queries=0)


# ---------------------------------------------------------------------------
# 3. BigQuery Result Parsing, Deduplication & RRF Scoring Tests
# ---------------------------------------------------------------------------

def test_fuse_and_deduplicate_empty():
    """Empty BigQuery result returns empty candidates list."""
    assert fuse_and_deduplicate([]) == []


def test_fuse_and_deduplicate_single_query():
    """Single query converts distance to similarity and computes RRF."""
    rows = [
        DummyRow(
            query_id=0,
            chunk_id="NCT001::overview::0",
            nct_id="NCT001",
            chunk_text="Trial 1 overview text",
            chunk_type="overview",
            distance=0.15,
        ),
        DummyRow(
            query_id=0,
            chunk_id="NCT002::overview::0",
            nct_id="NCT002",
            chunk_text="Trial 2 overview text",
            chunk_type="overview",
            distance=0.40,
        ),
    ]
    candidates = fuse_and_deduplicate(rows)
    assert len(candidates) == 2

    # Rank 0 should have higher RRF
    c1 = candidates[0]
    assert c1.nct_id == "NCT001"
    assert pytest.approx(c1.best_sim, 0.01) == 0.85  # 1.0 - 0.15
    assert pytest.approx(c1.rrf, 0.0001) == 1.0 / 60
    assert c1.chunk_ids == ["NCT001::overview::0"]

    c2 = candidates[1]
    assert c2.nct_id == "NCT002"
    assert pytest.approx(c2.best_sim, 0.01) == 0.60  # 1.0 - 0.40
    assert pytest.approx(c2.rrf, 0.0001) == 1.0 / 61


def test_fuse_and_deduplicate_multiple_queries_and_evidence_aggregation():
    """Candidate appearing in both queries accumulates RRF and gathers distinct chunk IDs."""
    rows = [
        # Query 0
        DummyRow(
            query_id=0,
            chunk_id="NCT001::overview::0",
            nct_id="NCT001",
            chunk_text="Trial 1 overview",
            chunk_type="overview",
            distance=0.20,
        ),
        # Query 1 returns a second chunk for the same trial at rank 0
        DummyRow(
            query_id=1,
            chunk_id="NCT001::inclusion::0",
            nct_id="NCT001",
            chunk_text="Trial 1 inclusion",
            chunk_type="inclusion",
            distance=0.10,
        ),
    ]
    candidates = fuse_and_deduplicate(rows)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.nct_id == "NCT001"
    assert "NCT001::overview::0" in c.chunk_ids
    assert "NCT001::inclusion::0" in c.chunk_ids
    # RRF should combine across both queries: 1/60 + 1/60
    assert pytest.approx(c.rrf, 0.0001) == (1.0 / 60) + (1.0 / 60)
    # Best similarity should be 1.0 - 0.10 = 0.90
    assert pytest.approx(c.best_sim, 0.01) == 0.90


# ---------------------------------------------------------------------------
# 4. Error Handling Tests (BigQuery Failures)
# ---------------------------------------------------------------------------

def test_execute_vector_search_not_found():
    """NotFound exception is wrapped in a clear RuntimeError."""
    mock_client = MagicMock()
    mock_client.query.side_effect = gcp_exceptions.NotFound("Table not found")

    with pytest.raises(RuntimeError, match="BigQuery resource not found"):
        execute_vector_search(mock_client, [[0.1] * 768], top_k=5)


def test_execute_vector_search_forbidden():
    """Forbidden exception is wrapped in a clear PermissionError."""
    mock_client = MagicMock()
    mock_client.query.side_effect = gcp_exceptions.Forbidden("Access denied")

    with pytest.raises(PermissionError, match="Permission denied accessing BigQuery table"):
        execute_vector_search(mock_client, [[0.1] * 768], top_k=5)


def test_execute_vector_search_bad_request():
    """BadRequest exception is wrapped in a clear RuntimeError."""
    mock_client = MagicMock()
    mock_client.query.side_effect = gcp_exceptions.BadRequest("Invalid SQL")

    with pytest.raises(RuntimeError, match="BadRequest"):
        execute_vector_search(mock_client, [[0.1] * 768], top_k=5)


# ---------------------------------------------------------------------------
# 5. Full Retrieve Function Tests with Mocking
# ---------------------------------------------------------------------------

def test_retrieve_empty_queries():
    """Empty or whitespace queries return empty list immediately."""
    assert retrieve([]) == []
    assert retrieve(["", "   "]) == []


@patch("app.services.retriever.embed")
def test_retrieve_pipeline_integration(mock_embed):
    """Retrieve calls embed, queries BigQuery, and returns sorted candidates."""
    mock_embed.return_value = [[0.1] * 768, [0.2] * 768]

    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_job.result.return_value = [
        DummyRow(
            query_id=0,
            chunk_id="NCT001::overview::0",
            nct_id="NCT001",
            chunk_text="Overview",
            chunk_type="overview",
            distance=0.10,
        )
    ]
    mock_client.query.return_value = mock_job
    set_bigquery_client(mock_client)

    try:
        candidates = retrieve(["breast cancer HER2", "patient case details"])
        assert len(candidates) == 1
        assert candidates[0].nct_id == "NCT001"
        assert candidates[0].chunk_ids == ["NCT001::overview::0"]
        assert pytest.approx(candidates[0].best_sim, 0.01) == 0.90
    finally:
        set_bigquery_client(None)

