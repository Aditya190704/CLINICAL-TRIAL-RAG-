from unittest.mock import MagicMock, patch

import pytest

from app.services.embeddings import _embed_batch


def test_invalid_embedding_response_is_not_retried():
    client = MagicMock()
    client.models.embed_content.side_effect = RuntimeError("invalid response shape")

    with patch("app.services.embeddings.settings.embedding_dim", 2):
        with pytest.raises(RuntimeError, match="Could not generate embeddings"):
            _embed_batch(client, ["cancer"], "RETRIEVAL_QUERY")

    assert client.models.embed_content.call_count == 1


def test_transient_embedding_error_is_retried_with_bounded_attempts():
    transient = RuntimeError("temporary service failure")
    transient.status_code = 503
    client = MagicMock()
    client.models.embed_content.side_effect = [
        transient,
        MagicMock(embeddings=[MagicMock(values=[3.0, 4.0])]),
    ]

    with (
        patch("app.services.embeddings.settings.embedding_dim", 2),
        patch("app.services.embeddings.time.sleep"),
    ):
        result = _embed_batch(client, ["cancer"], "RETRIEVAL_QUERY")

    assert client.models.embed_content.call_count == 2
    assert result == [[0.6, 0.8]]
