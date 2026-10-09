import numpy as np
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

_client = genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)
BATCH = 10


@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=2, max=30))
def _embed_batch(texts: list[str], task_type: str):
    return _client.models.embed_content(
        model=settings.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type, output_dimensionality=settings.embedding_dim
        ),
    )


def embed(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """task_type: RETRIEVAL_DOCUMENT for indexing, RETRIEVAL_QUERY for queries."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        resp = _embed_batch(texts[i : i + BATCH], task_type)
        vectors.extend(e.values for e in resp.embeddings)
    arr = np.array(vectors, dtype="float32")
    arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12   # unit-normalise for dot product
    return arr.tolist()