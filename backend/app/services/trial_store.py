
"""Load processed clinical-trial records and chunks from GCS or local files."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.cloud import storage

from app.config import settings

logger = logging.getLogger(__name__)

TRIALS_FILENAME = "trials.json"
CHUNKS_FILENAME = "chunks.json"


def _processed_dir() -> Path:
    """Return the configured local directory for processed JSON files."""
    return Path(settings.processed_dir)


def _gcs_object_candidates(filename: str) -> list[str]:
    """Return supported GCS paths, preferring the configured prefix."""
    prefix = str(settings.gcs_prefix or "").strip("/")
    candidates: list[str] = []

    if prefix:
        candidates.extend(
            [
                f"{prefix}/{filename}",
                f"{prefix}/processed/{filename}",
            ]
        )

    candidates.append(filename)

    # Preserve order and remove duplicate paths.
    return list(dict.fromkeys(candidates))


def _read_gcs_json(filename: str) -> Any | None:
    """Read JSON from GCS. Return None when no matching object exists."""
    bucket_name = str(settings.gcs_bucket or "").strip()

    if not bucket_name:
        return None

    client = storage.Client(project=settings.gcp_project)

    try:
        bucket = client.bucket(bucket_name)

        for object_name in _gcs_object_candidates(filename):
            blob = bucket.blob(object_name)

            try:
                if not blob.exists():
                    continue

                content = blob.download_as_text(encoding="utf-8")
                return json.loads(content)

            except json.JSONDecodeError as exc:
                logger.error(
                    "Invalid JSON in GCS object %s (%s).",
                    object_name,
                    type(exc).__name__,
                )
                raise RuntimeError(
                    f"The stored file {filename} contains invalid JSON."
                ) from exc

        return None

    finally:
        client.close()


def _read_local_json(filename: str) -> Any | None:
    """Read JSON from the configured local processed directory."""
    file_path = _processed_dir() / filename

    if not file_path.is_file():
        return None

    try:
        with file_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid JSON in local processed file %s (%s).",
            filename,
            type(exc).__name__,
        )
        raise RuntimeError(
            f"The local processed file {filename} contains invalid JSON."
        ) from exc


def _load_json(filename: str) -> Any:
    """Prefer GCS, then fall back to local processed files."""
    if settings.gcs_bucket:
        try:
            data = _read_gcs_json(filename)

            if data is not None:
                logger.info("Loaded %s from GCS.", filename)
                return data

            logger.warning(
                "GCS object for %s was not found; "
                "trying the local processed directory.",
                filename,
            )

        except RuntimeError:
            raise

        except Exception as exc:
            logger.warning(
                "GCS read failed for %s (%s); trying local storage.",
                filename,
                type(exc).__name__,
            )

    data = _read_local_json(filename)

    if data is not None:
        logger.info("Loaded %s from local processed storage.", filename)
        return data

    raise FileNotFoundError(
        f"Could not find {filename} in the configured GCS locations "
        f"or local directory {_processed_dir()}."
    )


def _extract_records(
    data: Any,
    filename: str,
) -> list[dict[str, Any]]:
    """Normalize list-based and dictionary-based JSON into records."""

    # Format 1: a JSON array of records.
    if isinstance(data, list):
        records = data

    elif isinstance(data, dict):
        # Format 2: records wrapped in a named list.
        records = None

        expected_fields = (
            ("trials", "items", "records", "data")
            if filename == TRIALS_FILENAME
            else ("chunks", "items", "records", "data")
        )

        for field in expected_fields:
            value = data.get(field)

            if isinstance(value, list):
                records = value
                break

        # Format 3: chunks.json is a dictionary keyed by chunk ID.
        #
        # Example:
        # {
        #   "NCT07601178::overview::0": {
        #       "nct_id": "NCT07601178",
        #       "type": "overview",
        #       "text": "..."
        #   }
        # }
        if records is None and filename == CHUNKS_FILENAME:
            if data and all(
                isinstance(value, dict)
                and {
                    "nct_id",
                    "type",
                    "text",
                }.issubset(value.keys())
                for value in data.values()
            ):
                records = []

                for chunk_id, value in data.items():
                    record = dict(value)

                    # Keep the existing ID if one is already present.
                    record.setdefault("chunk_id", chunk_id)

                    # Preserve the dictionary key as a fallback ID.
                    records.append(record)

    else:
        records = None

    if not isinstance(records, list):
        root_keys = (
            list(data.keys())[:10]
            if isinstance(data, dict)
            else []
        )

        raise RuntimeError(
            f"{filename} has an unsupported JSON structure. "
            f"Expected a list or supported dictionary format. "
            f"Root keys: {root_keys}"
        )

    if not all(isinstance(record, dict) for record in records):
        raise RuntimeError(
            f"{filename} contains one or more records "
            "that are not JSON objects."
        )

    return records


def _load_records(filename: str) -> list[dict[str, Any]]:
    """Load records and normalize NCT identifiers."""
    data = _load_json(filename)
    records = _extract_records(data, filename)

    for record in records:
        nct_id = str(record.get("nct_id") or "").strip().upper()

        if nct_id:
            record["nct_id"] = nct_id

    return records


@lru_cache(maxsize=1)
def trials() -> list[dict[str, Any]]:
    """Return unique processed clinical-trial metadata records."""
    records = _load_records(TRIALS_FILENAME)

    seen_ids: set[str] = set()
    unique_records: list[dict[str, Any]] = []

    for record in records:
        nct_id = str(record.get("nct_id") or "").strip().upper()

        if not nct_id:
            logger.warning(
                "Skipping a processed trial without an NCT identifier."
            )
            continue

        if nct_id in seen_ids:
            logger.warning("Skipping a duplicate processed trial record.")
            continue

        seen_ids.add(nct_id)
        unique_records.append(record)

    logger.info(
        "Loaded %d processed trial records.",
        len(unique_records),
    )
    return unique_records


@lru_cache(maxsize=1)
def chunks() -> list[dict[str, Any]]:
    """Return unique processed chunks for evidence and citation lookup."""
    records = _load_records(CHUNKS_FILENAME)

    seen_chunk_ids: set[str] = set()
    unique_records: list[dict[str, Any]] = []

    for record in records:
        chunk_id = str(record.get("chunk_id") or "").strip()
        nct_id = str(record.get("nct_id") or "").strip().upper()

        if not chunk_id:
            logger.warning(
                "Skipping a processed chunk without a chunk ID."
            )
            continue

        if not nct_id:
            logger.warning("Skipping a processed chunk without an NCT identifier.")
            continue

        if chunk_id in seen_chunk_ids:
            logger.warning("Skipping a duplicate processed chunk record.")
            continue

        record["chunk_id"] = chunk_id
        record["nct_id"] = nct_id

        seen_chunk_ids.add(chunk_id)
        unique_records.append(record)

    logger.info(
        "Loaded %d processed text chunks.",
        len(unique_records),
    )
    return unique_records


def clear_store_cache() -> None:
    """Clear cached data after re-ingestion or processed-file updates."""
    trials.cache_clear()
    chunks.cache_clear()

    logger.info("Cleared processed trial-store caches.")
