"""Unit tests for ingestion and duplicate prevention logic."""
from unittest.mock import MagicMock
import pytest

from ingestion.ingest import validate_records, get_existing_chunk_ids


def test_validate_records_success():
    """Valid records pass with no rejections."""
    records = [
        {
            "chunk_id": "NCT001::overview::0",
            "nct_id": "NCT001",
            "chunk_text": "Sample text",
            "chunk_type": "overview",
            "embedding": [0.1] * 768,
            "metadata_json": "{}",
        }
    ]
    valid, rejected = validate_records(records, expected_dim=768)
    assert len(valid) == 1
    assert len(rejected) == 0


def test_validate_records_missing_fields():
    """Missing chunk_id, nct_id, or empty text is rejected."""
    records = [
        {
            "chunk_id": "",
            "nct_id": "NCT001",
            "chunk_text": "Text",
            "embedding": [0.1] * 768,
        },
        {
            "chunk_id": "NCT002::overview::0",
            "nct_id": "NCT002",
            "chunk_text": "   ",  # whitespace only
            "embedding": [0.1] * 768,
        },
    ]
    valid, rejected = validate_records(records, expected_dim=768)
    assert len(valid) == 0
    assert len(rejected) == 2


def test_validate_records_dimension_mismatch():
    """Wrong embedding dimension is rejected."""
    records = [
        {
            "chunk_id": "NCT001::overview::0",
            "nct_id": "NCT001",
            "chunk_text": "Text",
            "embedding": [0.1] * 512,  # Expected 768
        }
    ]
    valid, rejected = validate_records(records, expected_dim=768)
    assert len(valid) == 0
    assert len(rejected) == 1
    assert "Dimension mismatch" in rejected[0]["reason"]


def test_validate_records_nan_inf():
    """Non-finite floats are rejected."""
    records = [
        {
            "chunk_id": "NCT001::overview::0",
            "nct_id": "NCT001",
            "chunk_text": "Text",
            "embedding": [float("nan")] * 768,
        }
    ]
    valid, rejected = validate_records(records, expected_dim=768)
    assert len(valid) == 0
    assert len(rejected) == 1
    assert "Non-finite" in rejected[0]["reason"]


def test_duplicate_safe_filtering():
    """Duplicate-safe logic filters out already existing chunks."""
    records = [
        {"chunk_id": "NCT001::overview::0", "nct_id": "NCT001"},
        {"chunk_id": "NCT001::inclusion::0", "nct_id": "NCT001"},
        {"chunk_id": "NCT002::overview::0", "nct_id": "NCT002"},
    ]
    existing_ids = {"NCT001::overview::0", "NCT002::overview::0"}

    to_write = [r for r in records if r["chunk_id"] not in existing_ids]
    assert len(to_write) == 1
    assert to_write[0]["chunk_id"] == "NCT001::inclusion::0"


def test_get_existing_chunk_ids_query():
    """get_existing_chunk_ids queries BigQuery and returns a set of chunk IDs."""
    mock_client = MagicMock()
    mock_table_ref = MagicMock()
    mock_table_ref.project = "test-proj"
    mock_table_ref.dataset_id = "clinical_trials"
    mock_table_ref.table_id = "trial_chunks"

    row1 = MagicMock()
    row1.chunk_id = "chunk_1"
    row2 = MagicMock()
    row2.chunk_id = "chunk_2"
    mock_client.query.return_value = [row1, row2]

    ids = get_existing_chunk_ids(mock_client, mock_table_ref)
    assert ids == {"chunk_1", "chunk_2"}

