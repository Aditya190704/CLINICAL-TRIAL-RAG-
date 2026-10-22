
"""Vertex AI text embeddings for clinical-trial retrieval."""

from __future__ import annotations

import logging
import math
import time
from typing import Literal, Sequence

from google import genai
from google.genai import types

from app.config import settings
from app.safe_logging import log_safe_error

logger = logging.getLogger(__name__)

# Keep requests within a low per-minute quota.
BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0
REQUEST_INTERVAL_SECONDS = 12.0

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


def _validate_task_type(task_type: str) -> TaskType:
    allowed = {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}

    if task_type not in allowed:
        raise ValueError(
            "task_type must be RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY."
        )

    return task_type  # type: ignore[return-value]


def _normalize_vector(
    values: Sequence[float],
    expected_dim: int,
) -> list[float]:
    """Validate an embedding vector and normalize it to unit length."""
    if len(values) != expected_dim:
        raise RuntimeError(
            f"Embedding dimension mismatch: received {len(values)}, "
            f"expected {expected_dim}. Check EMBEDDING_DIM and the index schema."
        )

    vector = [float(value) for value in values]

    if not all(math.isfinite(value) for value in vector):
        raise RuntimeError(
            "Embedding response contains non-finite values."
        )

    norm = math.sqrt(sum(value * value for value in vector))

    if norm == 0:
        raise RuntimeError(
            "Embedding service returned a zero-magnitude vector."
        )

    return [value / norm for value in vector]


def _embed_batch(
    client: genai.Client,
    texts: list[str],
    task_type: TaskType,
) -> list[list[float]]:
    """Embed a batch with exponential backoff for transient failures."""
    expected_dim = int(settings.embedding_dim)
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.embed_content(
                model=settings.embedding_model,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=expected_dim,
                ),
            )

            embeddings = getattr(response, "embeddings", None)

            if not embeddings or len(embeddings) != len(texts):
                raise RuntimeError(
                    "Embedding service returned an unexpected number "
                    "of vectors."
                )

            vectors: list[list[float]] = []

            for item in embeddings:
                values = getattr(item, "values", None)

                if values is None:
                    raise RuntimeError(
                        "Embedding response is missing vector values."
                    )

                vectors.append(
                    _normalize_vector(values, expected_dim)
                )

            return vectors

        except Exception as exc:
            last_error = exc

            if attempt == MAX_RETRIES - 1:
                break

            # Short bounded backoff avoids a long request storm when quota is exhausted.
            delay = RETRY_DELAY_SECONDS * (2**attempt)

            log_safe_error(logger, request_id=None, step=f"embedding_retry_{attempt + 1}", error=exc)

            time.sleep(delay)

    log_safe_error(logger, request_id=None, step="embedding_batch", error=last_error or RuntimeError())

    raise RuntimeError(
        "Could not generate embeddings. Check Vertex AI quota, "
        "project, model availability, and region settings."
    ) from last_error


def embed(
    texts: Sequence[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Generate normalized embeddings in batches, preserving input order.

    RETRIEVAL_DOCUMENT is for indexing trial text.
    RETRIEVAL_QUERY is for embedding patient search queries.
    """
    validated_task_type = _validate_task_type(task_type)

    if isinstance(texts, str):
        raise ValueError(
            "texts must be a sequence of strings, not one string. "
            "Pass [text] to embed a single item."
        )

    clean_texts: list[str] = []

    for index, text in enumerate(texts):
        if not isinstance(text, str):
            raise ValueError(
                f"Input at position {index} must be a string."
            )

        cleaned = text.strip()

        if not cleaned:
            raise ValueError(
                f"Input at position {index} is empty."
            )

        clean_texts.append(cleaned)

    if not clean_texts:
        return []

    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
        http_options=types.HttpOptions(
            timeout=max(1, round(settings.adk_timeout_seconds * 1000))
        ),
    )

    all_vectors: list[list[float]] = []
    last_request_time: float | None = None

    try:
        total = len(clean_texts)

        for start in range(0, total, BATCH_SIZE):
            batch = clean_texts[start : start + BATCH_SIZE]

            # Pace requests to reduce quota bursts.
            if last_request_time is not None:
                elapsed = time.monotonic() - last_request_time
                wait_time = REQUEST_INTERVAL_SECONDS - elapsed

                if wait_time > 0:
                    time.sleep(wait_time)

            logger.info(
                "Embedding batch %d/%d (%d texts).",
                start // BATCH_SIZE + 1,
                math.ceil(total / BATCH_SIZE),
                len(batch),
            )

            vectors = _embed_batch(
                client=client,
                texts=batch,
                task_type=validated_task_type,
            )

            last_request_time = time.monotonic()
            all_vectors.extend(vectors)

            logger.info(
                "Embedded %d/%d chunks.",
                len(all_vectors),
                total,
            )

        if len(all_vectors) != total:
            raise RuntimeError(
                "The number of generated vectors does not match "
                "the input count."
            )

        return all_vectors

    finally:
        client.close()
