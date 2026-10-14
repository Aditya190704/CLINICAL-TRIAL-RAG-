
"""Google Cloud Storage helpers for JSON-based clinical-trial data."""

from __future__ import annotations

import json
import logging
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import storage

from app.config import settings

logger = logging.getLogger(__name__)


def _get_bucket_name() -> str:
    bucket_name = str(settings.gcs_bucket or "").strip()

    if not bucket_name:
        raise RuntimeError(
            "GCS_BUCKET is not configured. Set it in the environment."
        )

    return bucket_name


def _get_object_name(filename: str) -> str:
    """Resolve an object name relative to the configured GCS prefix."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A non-empty GCS object name is required.")

    object_name = filename.strip().replace("\\", "/").lstrip("/")

    parts = object_name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid GCS object path.")

    prefix = str(settings.gcs_prefix or "").strip("/")
    if prefix:
        # Avoid adding the prefix twice when callers already provide it.
        if object_name == prefix or object_name.startswith(prefix + "/"):
            return object_name

        return f"{prefix}/{object_name}"

    return object_name


def read_json(filename: str) -> Any | None:
    """Read and decode a JSON object.

    Returns None only when the requested object does not exist.
    Authentication, permission, network, and JSON errors are raised.
    """
    bucket_name = _get_bucket_name()
    object_name = _get_object_name(filename)

    client = storage.Client(project=settings.gcp_project)

    try:
        blob = client.bucket(bucket_name).blob(object_name)

        try:
            content = blob.download_as_text(encoding="utf-8")
        except NotFound:
            logger.info("GCS object not found: %s", object_name)
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in GCS object %s.", object_name)
            raise ValueError(
                f"GCS object '{object_name}' does not contain valid JSON."
            ) from exc

    finally:
        client.close()


def write_json(
    filename: str,
    data: Any,
    *,
    overwrite: bool = True,
) -> str:
    """Serialize and upload JSON to GCS.

    Args:
        filename: Object name relative to GCS_PREFIX, or a fully prefixed name.
        data: JSON-serializable Python data.
        overwrite: If False, fail if the object already exists.

    Returns:
        The fully resolved GCS object name.
    """
    bucket_name = _get_bucket_name()
    object_name = _get_object_name(filename)

    try:
        content = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("The supplied data cannot be serialized as valid JSON.") from exc

    client = storage.Client(project=settings.gcp_project)

    try:
        blob = client.bucket(bucket_name).blob(object_name)

        # A generation precondition prevents accidental overwrites.
        if overwrite:
            blob.upload_from_string(
                content,
                content_type="application/json; charset=utf-8",
            )
        else:
            blob.upload_from_string(
                content,
                content_type="application/json; charset=utf-8",
                if_generation_match=0,
            )

        logger.info("Uploaded JSON object to GCS: %s", object_name)
        return object_name

    finally:
        client.close()


def object_exists(filename: str) -> bool:
    """Check whether a GCS object exists."""
    bucket_name = _get_bucket_name()
    object_name = _get_object_name(filename)

    client = storage.Client(project=settings.gcp_project)

    try:
        return client.bucket(bucket_name).blob(object_name).exists()
    finally:
        client.close()


def delete_object(filename: str) -> bool:
    """Delete an object if it exists.

    Returns True when deleted and False when the object was absent.
    """
    bucket_name = _get_bucket_name()
    object_name = _get_object_name(filename)

    client = storage.Client(project=settings.gcp_project)

    try:
        blob = client.bucket(bucket_name).blob(object_name)

        try:
            blob.delete()
            logger.info("Deleted GCS object: %s", object_name)
            return True
        except NotFound:
            return False

    finally:
        client.close()
