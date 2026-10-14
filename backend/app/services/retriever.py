
"""BigQuery Vector Search retrieval with Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from google.cloud import bigquery

from app.config import settings
from app.services.embeddings import embed

logger = logging.getLogger(__name__)

RRF_K = 60
MAX_SEARCH_QUERIES = 5


@dataclass
class Candidate:
    """A trial retrieved from one or more search queries."""

    nct_id: str
    rrf: float = 0.0
    best_sim: float = 0.0
    chunk_ids: list[str] = field(default_factory=list)


def _table_ref() -> str:
    project = settings.gcp_project
    dataset = settings.bigquery_dataset
    table = settings.bigquery_chunks_table

    if not project or not dataset or not table:
        raise RuntimeError(
            "BigQuery retrieval configuration is incomplete. Check "
            "GCP_PROJECT, BIGQUERY_DATASET, and BIGQUERY_CHUNKS_TABLE."
        )

    # This reference comes from application configuration, not user input.
    return f"`{project}.{dataset}.{table}`"


def validate_embeddings(
    vectors: list[list[float]],
    expected_dim: int | None = None,
) -> list[list[float]]:
    """Validate and normalize query embeddings before sending them to BigQuery."""
    if not vectors:
        raise ValueError("No query embeddings were generated.")

    dimension = expected_dim or int(settings.embedding_dim)
    validated: list[list[float]] = []

    for index, vector in enumerate(vectors):
        if not isinstance(vector, (list, tuple)):
            raise ValueError(f"Embedding {index} is not a vector.")

        if len(vector) != dimension:
            raise ValueError(
                f"Embedding {index} has dimension {len(vector)}; "
                f"expected {dimension}."
            )

        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Embedding {index} contains invalid values.") from exc

        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Embedding {index} contains non-finite values.")

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            raise ValueError(f"Embedding {index} has zero magnitude.")

        validated.append([value / norm for value in values])

    return validated


def build_vector_search_sql(
    query_count: int,
    top_k: int,
) -> str:
    """Build a parameterized Vector Search query for multiple search strings."""
    if query_count < 1 or query_count > MAX_SEARCH_QUERIES:
        raise ValueError(
            f"Search query count must be between 1 and {MAX_SEARCH_QUERIES}."
        )

    if top_k < 1:
        raise ValueError("top_k must be greater than zero.")

    table = _table_ref()
    parts: list[str] = []

    for query_index in range(query_count):
        parts.append(
            f"""
            SELECT
                {query_index} AS query_id,
                CAST(base.chunk_id AS STRING) AS chunk_id,
                UPPER(CAST(base.nct_id AS STRING)) AS nct_id,
                distance
            FROM VECTOR_SEARCH(
                TABLE {table},
                'embedding',
                (SELECT @q{query_index} AS query_vector),
                query_column_to_search => 'query_vector',
                top_k => @top_k,
                distance_type => 'COSINE'
            )
            """
        )

    return "\nUNION ALL\n".join(parts)


def _safe_similarity(distance: Any) -> float:
    """Convert cosine distance to a bounded similarity score."""
    try:
        distance_value = float(distance)
    except (TypeError, ValueError):
        return 0.0

    if not math.isfinite(distance_value):
        return 0.0

    return max(0.0, min(1.0, 1.0 - distance_value))


def fuse_and_deduplicate(rows: list[Any]) -> list[Candidate]:
    """Fuse per-query rankings using Reciprocal Rank Fusion.

    Each query contributes 1 / (RRF_K + rank) to a trial. Duplicate chunks
    within the same query do not receive multiple contributions.
    """
    if not rows:
        return []

    normalized_rows: list[dict[str, Any]] = []

    for row in rows:
        try:
            query_id = int(row["query_id"])
            nct_id = str(row["nct_id"]).strip().upper()
            chunk_id = str(row["chunk_id"]).strip()
            distance = float(row["distance"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue

        if not nct_id or not chunk_id or not math.isfinite(distance):
            continue

        normalized_rows.append(
            {
                "query_id": query_id,
                "nct_id": nct_id,
                "chunk_id": chunk_id,
                "distance": distance,
                "similarity": _safe_similarity(distance),
            }
        )

    # Assign a rank within each query because UNION ALL does not guarantee
    # that the combined result set preserves Vector Search ordering.
    grouped_by_query: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for row in normalized_rows:
        grouped_by_query[row["query_id"]].append(row)

    trial_scores: dict[str, float] = defaultdict(float)
    best_similarity: dict[str, float] = defaultdict(float)
    chunk_similarity: dict[tuple[str, str], float] = {}
    seen_query_chunks: set[tuple[int, str, str]] = set()

    for query_id, query_rows in grouped_by_query.items():
        query_rows.sort(key=lambda row: row["distance"])

        for rank, row in enumerate(query_rows, start=1):
            nct_id = row["nct_id"]
            chunk_id = row["chunk_id"]

            query_chunk_key = (query_id, nct_id, chunk_id)
            if query_chunk_key in seen_query_chunks:
                continue

            seen_query_chunks.add(query_chunk_key)

            trial_scores[nct_id] += 1.0 / (RRF_K + rank)
            best_similarity[nct_id] = max(
                best_similarity[nct_id],
                row["similarity"],
            )

            chunk_key = (nct_id, chunk_id)
            chunk_similarity[chunk_key] = max(
                chunk_similarity.get(chunk_key, 0.0),
                row["similarity"],
            )

    chunk_ids_by_trial: dict[str, list[str]] = defaultdict(list)

    ranked_chunks = sorted(
        chunk_similarity.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    for (nct_id, chunk_id), _score in ranked_chunks:
        if chunk_id not in chunk_ids_by_trial[nct_id]:
            chunk_ids_by_trial[nct_id].append(chunk_id)

    candidates = [
        Candidate(
            nct_id=nct_id,
            rrf=score,
            best_sim=best_similarity[nct_id],
            chunk_ids=chunk_ids_by_trial[nct_id],
        )
        for nct_id, score in trial_scores.items()
    ]

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.rrf,
            candidate.best_sim,
        ),
        reverse=True,
    )


def retrieve(
    queries: list[str],
    top_k: int | None = None,
) -> list[Candidate]:
    """Retrieve and fuse clinical-trial candidates for one or more queries."""
    if isinstance(queries, str):
        queries = [queries]

    if not queries:
        return []

    clean_queries: list[str] = []
    for query in queries:
        if not isinstance(query, str):
            continue

        cleaned = query.strip()
        if cleaned and cleaned not in clean_queries:
            clean_queries.append(cleaned)

    if not clean_queries:
        return []

    clean_queries = clean_queries[:MAX_SEARCH_QUERIES]
    effective_top_k = int(top_k or settings.top_k_chunks)

    if effective_top_k < 1:
        raise ValueError("top_k must be greater than zero.")

    try:
        raw_vectors = embed(
            clean_queries,
            task_type="RETRIEVAL_QUERY",
        )
        vectors = validate_embeddings(raw_vectors)
    except Exception as exc:
        logger.error(
            "Query embedding failed (%s).",
            type(exc).__name__,
        )
        raise RuntimeError(
            "Could not create search embeddings. Please try again later."
        ) from exc

    if len(vectors) != len(clean_queries):
        raise RuntimeError(
            "The embedding service returned a different number of vectors "
            "than the number of search queries."
        )

    sql = build_vector_search_sql(
        query_count=len(vectors),
        top_k=effective_top_k,
    )

    parameters: list[bigquery.QueryParameter] = [
        bigquery.ScalarQueryParameter(
            "top_k",
            "INT64",
            effective_top_k,
        )
    ]

    for index, vector in enumerate(vectors):
        parameters.append(
            bigquery.ArrayQueryParameter(
                f"q{index}",
                "FLOAT64",
                vector,
            )
        )

    client = bigquery.Client(
        project=settings.gcp_project,
        location=settings.bq_location,
    )

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=parameters,
        )

        rows = list(
            client.query(
                sql,
                job_config=job_config,
            ).result()
        )

        candidates = fuse_and_deduplicate(rows)

        logger.info(
            "Vector retrieval completed: queries=%d, candidates=%d.",
            len(clean_queries),
            len(candidates),
        )

        return candidates

    except Exception as exc:
        logger.error(
            "BigQuery Vector Search failed (%s).",
            type(exc).__name__,
        )
        raise RuntimeError(
            "Clinical-trial retrieval failed. Check BigQuery access, "
            "the vector index, and the configured table."
        ) from exc

    finally:
        client.close()
