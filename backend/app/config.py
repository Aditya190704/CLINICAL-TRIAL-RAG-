from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    gcp_project: str
    gcp_location: str = "us-central1"
    embedding_model: str = "text-embedding-005"
    embedding_dim: int = 768
    gemini_model: str = "gemini-2.5-flash"

    index_id: str = ""
    index_endpoint_id: str = ""
    deployed_index_id: str = "clinical_trials_deployed"

    gcs_bucket: str = ""          # empty = use local files only
    gcs_prefix: str = "clinical-trials"

    top_k_chunks: int = 40          # neighbours per query
    candidates_to_judge: int = 6    # trials sent to the LLM judge
    final_results: int = 3

    raw_dir: Path = BASE_DIR / "data" / "raw"
    processed_dir: Path = BASE_DIR / "data" / "processed"


settings = Settings()