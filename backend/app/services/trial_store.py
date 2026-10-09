import json
from functools import lru_cache

from app.config import settings


def _load(name: str):
    """Prefer GCS when configured, fall back to local file."""
    if settings.gcs_bucket:
        try:
            from app.services.gcs_store import download_json
            return download_json(name)
        except Exception as e:
            print(f"GCS read failed for {name} ({e}); using local copy")
    with open(settings.processed_dir / name, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def trials() -> dict[str, dict]:
    return {t["nct_id"]: t for t in _load("trials.json")}


@lru_cache(maxsize=1)
def chunks() -> dict[str, dict]:
    return _load("chunks.json")