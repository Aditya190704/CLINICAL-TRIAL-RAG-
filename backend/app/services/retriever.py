"""BigQuery Vector Search Retriever for Clinical Trials.

Replaces Vertex AI Vector Search endpoint calls with Google Cloud BigQuery
VECTOR_SEARCH() exact cosine distance similarity search.
"""
from collections import defaultdict
from dataclasses import dataclass, field
import json
import logging
import math
from typing import Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import bigquery

from app.config import settings
from app.services.embeddings import embed
from app.services.trial_store import chunks

logger = logging.getLogger(__name__)

# Reusable BigQuery client instance
_client: Optional[bigquery.Client] = None


def get_bigquery_client() -> bigquery.Client:
    """Lazily initialize and return the BigQuery client."""
    global _client
    if _client is None:
        if not settings.gcp_project:
            raise ValueError(
                "GCP project ID is not configured. Set GCP_PROJECT in backend/.env"
            )
        _client = bigquery.Client(
            project=settings.gcp_project,
            location=settings.bq_location,
        )
    return _client


def set_bigquery_client(client: Optional[bigquery.Client]) -> None:
    """Override the BigQuery client instance (useful for unit testing)."""
    global _client
    _client = client


@dataclass
class Candidate:
    """Trial candidate with fused relevance and evidence chunk IDs."""
    nct_id: str
    rrf: float = 0.0
    best_sim: float = 0.0
    chunk_ids: list[str] = field(default_factory=list)


def validate_embeddings(vectors: list[list[float]], expected_dim: int) -> None:
    """Validate vector dimensions, non-emptiness, and numerical values."""
    if not vectors:
        raise ValueError("Cannot perform vector search with empty vectors list.")

    for idx, vec in enumerate(vectors):
        if not isinstance(vec, (list, tuple)):
            raise ValueError(f"Vector at index {idx} must be a list/sequence of numbers.")
        if len(vec) != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch at index {idx}: expected {expected_dim}, "
                f"got {len(vec)}."
            )
        for dim_idx, val in enumerate(vec):
            if val is None or math.isnan(val) or math.isinf(val):
                raise ValueError(
                    f"Vector at index {idx} contains invalid numerical value {val} at dimension {dim_idx}."
                )


def build_vector_search_sql(
    project_id: str,
    dataset_id: str,
    table_id: str,
    num_queries: int,
) -> str:
    """Construct a parameterized BigQuery VECTOR_SEARCH GoogleSQL query."""
    if num_queries <= 0:
        raise ValueError("num_queries must be greater than 0")

    # Construct the query table subquery with UNION ALL for batch queries
    subquery_parts = [
        f"SELECT {i} AS query_id, @q{i} AS query_vector"
        for i in range(num_queries)
    ]
    query_subquery = "\n      UNION ALL\n      ".join(subquery_parts)

    full_table_path = f"`{project_id}.{dataset_id}.{table_id}`"

    sql = f"""
SELECT
  query.query_id AS query_id,
  base.chunk_id AS chunk_id,
  base.nct_id AS nct_id,
  base.chunk_text AS chunk_text,
  base.chunk_type AS chunk_type,
  base.metadata_json AS metadata_json,
  distance
FROM VECTOR_SEARCH(
  TABLE {full_table_path},
  'embedding',
  (
    {query_subquery}
  ),
  query_column_to_search => 'query_vector',
  top_k => @top_k,
  distance_type => 'COSINE'
)
ORDER BY query.query_id, distance ASC
"""
    return sql.strip()


def execute_vector_search(
    client: bigquery.Client,
    vectors: list[list[float]],
    top_k: int,
) -> list[bigquery.Row]:
    """Execute VECTOR_SEARCH against the configured BigQuery table."""
    project = settings.gcp_project
    dataset = settings.bigquery_dataset
    table = settings.bigquery_chunks_table

    sql = build_vector_search_sql(
        project_id=project,
        dataset_id=dataset,
        table_id=table,
        num_queries=len(vectors),
    )

    query_params: list[bigquery.ArrayQueryParameter | bigquery.ScalarQueryParameter] = [
        bigquery.ArrayQueryParameter(f"q{i}", "FLOAT64", [float(x) for x in vectors[i]])
        for i in range(len(vectors))
    ]
    query_params.append(bigquery.ScalarQueryParameter("top_k", "INT64", top_k))

    job_config = bigquery.QueryJobConfig(
        query_parameters=query_params,
        default_dataset=f"{project}.{dataset}",
    )

    try:
        query_job = client.query(sql, job_config=job_config, location=settings.bq_location)
        rows = list(query_job.result())
        return rows
    except gcp_exceptions.NotFound as e:
        msg = (
            f"BigQuery resource not found: `{project}.{dataset}.{table}` in location "
            f"'{settings.bq_location}'. Ensure the dataset and table are created and populated. "
            f"Original error: {e}"
        )
        logger.error(msg)
        raise RuntimeError(msg) from e
    except gcp_exceptions.Forbidden as e:
        msg = (
            f"Permission denied accessing BigQuery table `{project}.{dataset}.{table}`. "
            f"Ensure your GCP credentials or Service Account has BigQuery Data Viewer and "
            f"BigQuery Job User roles. Original error: {e}"
        )
        logger.error(msg)
        raise PermissionError(msg) from e
    except gcp_exceptions.BadRequest as e:
        msg = f"BigQuery vector search query failed (BadRequest): {e}"
        logger.error(msg)
        raise RuntimeError(msg) from e
    except gcp_exceptions.GoogleAPICallError as e:
        msg = f"BigQuery vector search API call failed: {e}"
        logger.error(msg)
        raise RuntimeError(msg) from e
    except Exception as e:
        msg = f"Unexpected error during BigQuery vector search: {e}"
        logger.error(msg)
        raise RuntimeError(msg) from e


def fuse_and_deduplicate(rows: list[bigquery.Row]) -> list[Candidate]:
    """Process BigQuery vector search rows with Reciprocal Rank Fusion and NCT deduplication.

    For cosine distance, similarity is defined as max(0.0, 1.0 - distance).
    RRF score is calculated as 1.0 / (60 + rank) for the highest-ranking chunk
    of each trial per query.
    """
    if not rows:
        return []

    # Cache chunks locally in memory so pipeline.py can access text/type if needed
    try:
        chunk_cache = chunks()
    except Exception:
        chunk_cache = {}

    # Group rows by query_id
    grouped_by_query: dict[int, list[bigquery.Row]] = defaultdict(list)
    for row in rows:
        q_id = row.get("query_id", 0) if hasattr(row, "get") else getattr(row, "query_id", 0)
        grouped_by_query[q_id].append(row)

    candidates: dict[str, Candidate] = defaultdict(lambda: Candidate(nct_id=""))

    for q_id, q_rows in grouped_by_query.items():
        seen_trials_in_query: set[str] = set()

        for rank, row in enumerate(q_rows):
            cid = row.get("chunk_id") if hasattr(row, "get") else getattr(row, "chunk_id", None)
            nct = row.get("nct_id") if hasattr(row, "get") else getattr(row, "nct_id", None)
            chunk_text = row.get("chunk_text") if hasattr(row, "get") else getattr(row, "chunk_text", "")
            chunk_type = row.get("chunk_type") if hasattr(row, "get") else getattr(row, "chunk_type", "overview")
            distance = row.get("distance", 1.0) if hasattr(row, "get") else getattr(row, "distance", 1.0)

            if not nct or not cid:
                continue

            # Ensure chunk is available in chunks() cache for downstream passage extraction
            if cid not in chunk_cache and chunk_text:
                chunk_cache[cid] = {"nct_id": nct, "type": chunk_type, "text": chunk_text}

            # Convert cosine distance to cosine similarity
            # In BigQuery, COSINE distance = 1 - cosine_similarity
            similarity = max(0.0, 1.0 - float(distance))

            cand = candidates[nct]
            cand.nct_id = nct

            # Add chunk ID to evidence list if not already present
            if cid not in cand.chunk_ids:
                cand.chunk_ids.append(cid)

            # RRF score: count each trial once per query for its top-ranked chunk
            if nct not in seen_trials_in_query:
                cand.rrf += 1.0 / (60 + rank)
                seen_trials_in_query.add(nct)

            cand.best_sim = max(cand.best_sim, similarity)

    # Sort candidates by fused RRF score descending
    return sorted(candidates.values(), key=lambda c: c.rrf, reverse=True)


def retrieve(queries: list[str]) -> list[Candidate]:
    """Retrieve trial candidates matching the given patient queries using BigQuery VECTOR_SEARCH.

    Parameters:
        queries: List of query strings (e.g. [patient search query, case text]).

    Returns:
        List of Candidate objects sorted by RRF relevance descending.
    """
    valid_queries = [q.strip() for q in queries if q and q.strip()]
    if not valid_queries:
        logger.warning("Empty or whitespace-only queries provided to retrieve(); returning empty list.")
        return []

    # Generate embeddings using the existing embedding service
    vectors = embed(valid_queries, task_type="RETRIEVAL_QUERY")

    # Validate vector format and dimension
    validate_embeddings(vectors, expected_dim=settings.embedding_dim)

    # Get BigQuery client
    client = get_bigquery_client()

    # Execute search
    top_k = settings.top_k_chunks
    rows = execute_vector_search(client, vectors, top_k=top_k)

    # Fuse, deduplicate, and sort candidates
    return fuse_and_deduplicate(rows)