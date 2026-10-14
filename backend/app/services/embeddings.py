
"""Vertex AI text embeddings for clinical-trial retrieval."""

from __future__ import annotations

import logging
import math
import time
from typing import Literal, Sequence

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


def _validate_task_type(task_type: str) -> TaskType:
    allowed = {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}

    if task_type not in allowed:
        raise ValueError(
            "task_type must be RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY."
        )

    return task_type  # type: ignore[return-value]


def _normalize_vector(values: Sequence[float], expected_dim: int) -> list[float]:
    """Validate an embedding vector and normalize it to unit length."""
    if len(values) != expected_dim:
        raise RuntimeError(
            f"Embedding dimension mismatch: received {len(values)}, "
            f"expected {expected_dim}. Check EMBEDDING_DIM and the index schema."
        )

    vector = [float(value) for value in values]

    if not all(math.isfinite(value) for value in vector):
        raise RuntimeError("Embedding response contains non-finite values.")

    norm = math.sqrt(sum(value * value for value in vector))

    if norm == 0:
        raise RuntimeError("Embedding service returned a zero-magnitude vector.")

    return [value / norm for value in vector]


def _embed_batch(
    client: genai.Client,
    texts: list[str],
    task_type: TaskType,
) -> list[list[float]]:
    """Embed one batch, retrying transient failures a limited number of times."""
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
                    "Embedding service returned an unexpected number of vectors."
                )

            vectors: list[list[float]] = []

            for item in embeddings:
                values = getattr(item, "values", None)

                if values is None:
                    raise RuntimeError(
                        "Embedding response is missing vector values."
                    )

                vectors.append(_normalize_vector(values, expected_dim))

            return vectors

        except Exception as exc:
            last_error = exc

            if attempt == MAX_RETRIES - 1:
                break

            logger.warning(
                "Embedding request failed (attempt %d/%d, error=%s).",
                attempt + 1,
                MAX_RETRIES,
                type(exc).__name__,
            )

            time.sleep(RETRY_DELAY_SECONDS * (2**attempt))

    logger.error(
        "Embedding batch failed after %d attempts (%s).",
        MAX_RETRIES,
        type(last_error).__name__ if last_error else "unknown error",
    )

    raise RuntimeError(
        "Could not generate embeddings. Check Vertex AI access, model "
        "availability, region settings, and quota."
    ) from last_error


def embed(
    texts: Sequence[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Generate normalized embeddings in bounded batches.

    Args:
        texts: Documents or search queries to embed.
        task_type:
            RETRIEVAL_DOCUMENT when indexing trial text.
            RETRIEVAL_QUERY when searching for relevant trials.

    Returns:
        One unit-normalized embedding vector per input text, in input order.
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
            raise ValueError(f"Input at position {index} must be a string.")

        cleaned = text.strip()

        if not cleaned:
            raise ValueError(f"Input at position {index} is empty.")

        clean_texts.append(cleaned)

    if not clean_texts:
        return []

    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )

    all_vectors: list[list[float]] = []

    try:
        for start in range(0, len(clean_texts), BATCH_SIZE):
            batch = clean_texts[start : start + BATCH_SIZE]

            vectors = _embed_batch(
                client=client,
                texts=batch,
                task_type=validated_task_type,
            )

            all_vectors.extend(vectors)

        if len(all_vectors) != len(clean_texts):
            raise RuntimeError(
                "The number of generated vectors does not match the input count."
            )

        return all_vectors

    finally:
        client.close()
