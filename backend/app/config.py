
"""Centralized application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    # Google Cloud project and region
    gcp_project: str = Field(
        default="",
        validation_alias="GCP_PROJECT",
    )
    gcp_location: str = Field(
        default="us-central1",
        validation_alias="GCP_LOCATION",
    )

    # BigQuery configuration
    bigquery_dataset: str = Field(
        default="clinical_trials",
        validation_alias="BIGQUERY_DATASET",
    )
    bigquery_chunks_table: str = Field(
        default="trial_chunks",
        validation_alias="BIGQUERY_CHUNKS_TABLE",
    )
    bigquery_location: str | None = Field(
        default=None,
        validation_alias="BIGQUERY_LOCATION",
    )

    # Embedding configuration
    embedding_model: str = Field(
        default="text-embedding-005",
        validation_alias="EMBEDDING_MODEL",
    )
    embedding_dim: int = Field(
        default=768,
        ge=1,
        validation_alias="EMBEDDING_DIM",
    )

    # Gemini configuration
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias="GEMINI_MODEL",
    )

    # Retrieval and ranking
    top_k_chunks: int = Field(
        default=20,
        ge=1,
        le=500,
        validation_alias="CANDIDATES_TO_RETRIEVE",
    )
    candidates_to_judge: int = Field(
        default=6,
        ge=1,
        le=100,
        validation_alias="CANDIDATES_TO_JUDGE",
    )
    final_results: int = Field(
        default=3,
        ge=1,
        le=20,
        validation_alias="TOP_K_RESULTS",
    )

    # Workflow settings
    adk_concurrency: int = Field(
        default=6,
        ge=1,
        le=50,
        validation_alias="ADK_CONCURRENCY",
    )
    adk_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
        validation_alias="ADK_TIMEOUT_SECONDS",
    )
    adk_app_name: str = Field(
        default="clinical_trial_matcher",
        validation_alias="ADK_APP_NAME",
    )

    # Google Cloud Storage
    gcs_bucket: str = Field(
        default="",
        validation_alias="GCS_BUCKET",
    )
    gcs_prefix: str = Field(
        default="clinical-trials",
        validation_alias="GCS_PREFIX",
    )

    # Local processed and raw data directories
    processed_dir: Path = Field(
        default=BACKEND_DIR / "data" / "processed",
        validation_alias="PROCESSED_DIR",
    )
    raw_dir: Path = Field(
        default=BACKEND_DIR / "data" / "raw",
        validation_alias="RAW_DIR",
    )

    @property
    def bq_location(self) -> str:
        """Resolve the BigQuery job location."""
        return (
            self.bigquery_location.strip()
            if self.bigquery_location and self.bigquery_location.strip()
            else self.gcp_location
        )

    @field_validator(
        "gcp_project",
        "gcp_location",
        "bigquery_dataset",
        "bigquery_chunks_table",
        "embedding_model",
        "gemini_model",
        "adk_app_name",
    )
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("gcs_bucket", "gcs_prefix")
    @classmethod
    def strip_optional_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("gcs_prefix")
    @classmethod
    def normalize_gcs_prefix(cls, value: str) -> str:
        return value.strip("/")

    @field_validator("bigquery_location")
    @classmethod
    def normalize_bigquery_location(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()
        return cleaned or None


settings = Settings()
