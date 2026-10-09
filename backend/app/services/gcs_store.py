import json
from pathlib import Path
from google.cloud import storage
from app.config import settings


def _bucket():
    return storage.Client(project=settings.gcp_project).bucket(settings.gcs_bucket)


def _name(name: str) -> str:
    return f"{settings.gcs_prefix}/{name}"


def upload_file(local_path: Path, blob_name: str) -> str:
    blob = _bucket().blob(_name(blob_name))
    blob.upload_from_filename(str(local_path), content_type="application/json")
    return f"gs://{settings.gcs_bucket}/{_name(blob_name)}"


def download_json(blob_name: str):
    blob = _bucket().blob(_name(blob_name))
    return json.loads(blob.download_as_text(encoding="utf-8"))