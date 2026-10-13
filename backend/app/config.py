from typing import Optional
from pathlib import Path
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    gcp_project: str = Field(
        default="",
        validation_alias=AliasChoices("gcp_project", "GCP_PROJECT", "gcp_project_id", "GCP_PROJECT_ID"),
    )
    gcp_location: str = Field(
        default="us-central1",
        validation_alias=AliasChoices("gcp_location", "GCP_LOCATION"),
    )

    # BigQuery Vector Search Configuration
    bigquery_dataset: str = Field(
        default="clinical_trials",
        validation_alias=AliasChoices("bigquery_dataset", "BIGQUERY_DATASET"),
    )
    bigquery_chunks_table: str = Field(
        default="trial_chunks",
        validation_alias=AliasChoices("bigquery_chunks_table", "BIGQUERY_CHUNKS_TABLE"),
    )
    bigquery_location: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("bigquery_location", "BIGQUERY_LOCATION"),
    )

    embedding_model: str = Field(
        default="text-embedding-005",
        validation_alias=AliasChoices("embedding_model", "EMBEDDING_MODEL"),
    )
    embedding_dim: int = Field(
        default=768,
        validation_alias=AliasChoices("embedding_dim", "EMBEDDING_DIM"),
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("gemini_model", "GEMINI_MODEL"),
    )

    gcs_bucket: str = ""          # empty = use local files only
    gcs_prefix: str = "clinical-trials"

    top_k_chunks: int = Field(
        default=20,
        validation_alias=AliasChoices("top_k_chunks", "TOP_K_CHUNKS", "candidates_to_retrieve", "CANDIDATES_TO_RETRIEVE"),
    )
    candidates_to_judge: int = Field(
        default=6,
        validation_alias=AliasChoices("candidates_to_judge", "CANDIDATES_TO_JUDGE"),
    )
    final_results: int = Field(
        default=3,
        validation_alias=AliasChoices("final_results", "FINAL_RESULTS", "top_k_results", "TOP_K_RESULTS"),
    )

    # Google ADK Workflow Configuration
    adk_concurrency: int = Field(
        default=6,
        validation_alias=AliasChoices("adk_concurrency", "ADK_CONCURRENCY"),
    )
    adk_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("adk_timeout_seconds", "ADK_TIMEOUT_SECONDS"),
    )
    adk_app_name: str = Field(
        default="clinical_trial_matcher",
        validation_alias=AliasChoices("adk_app_name", "ADK_APP_NAME"),
    )

    raw_dir: Path = BASE_DIR / "data" / "raw"
    processed_dir: Path = BASE_DIR / "data" / "processed"

    @property
    def bq_location(self) -> str:
        """Effective BigQuery location: bigquery_location if set, else gcp_location."""
        return self.bigquery_location or self.gcp_location


settings = Settings()