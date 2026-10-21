"""Ingestion script for Clinical Trial RAG.

Chunks trials, generates dense vector embeddings via Vertex AI Embeddings,
and stores chunk records in Google Cloud BigQuery. It also updates the local
chunks.json cache and uploads trials.json and chunks.json to GCS when configured.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from typing import Any

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from app.config import settings
from app.services import gcs_store
from app.services.embeddings import embed
from ingestion.chunker import chunk_trial

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest")


def get_bigquery_table_ref(client: bigquery.Client) -> bigquery.TableReference:
    """Return the BigQuery TableReference for the trial_chunks table."""
    dataset_ref = bigquery.DatasetReference(
        settings.gcp_project,
        settings.bigquery_dataset,
    )
    return dataset_ref.table(settings.bigquery_chunks_table)


def ensure_table_exists(client: bigquery.Client) -> bigquery.Table:
    """Ensure the dataset and trial_chunks table exist in BigQuery."""
    dataset_ref = bigquery.DatasetReference(
        settings.gcp_project,
        settings.bigquery_dataset,
    )

    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        logger.info(
            "Dataset %s not found. Creating in %s...",
            settings.bigquery_dataset,
            settings.bq_location,
        )
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = settings.bq_location
        client.create_dataset(dataset, exists_ok=True)
        logger.info("Dataset %s created.", settings.bigquery_dataset)

    table_ref = get_bigquery_table_ref(client)
    schema = [
        bigquery.SchemaField(
            "chunk_id", "STRING", mode="REQUIRED",
            description="Unique chunk ID",
        ),
        bigquery.SchemaField(
            "nct_id", "STRING", mode="REQUIRED",
            description="NCT identifier",
        ),
        bigquery.SchemaField(
            "chunk_text", "STRING", mode="REQUIRED",
            description="Text content",
        ),
        bigquery.SchemaField(
            "chunk_type", "STRING", mode="NULLABLE",
            description="overview/inclusion/exclusion/publication",
        ),
        bigquery.SchemaField(
            "embedding", "FLOAT64", mode="REPEATED",
            description="Dense embedding vector",
        ),
        bigquery.SchemaField(
            "metadata_json", "STRING", mode="NULLABLE",
            description="JSON trial metadata",
        ),
    ]

    try:
        table = client.get_table(table_ref)
        logger.info("Found existing BigQuery table: %s", table_ref.path)
        return table
    except NotFound:
        logger.info("Creating BigQuery table: %s...", table_ref.path)
        table = bigquery.Table(table_ref, schema=schema)
        table = client.create_table(table)
        logger.info("Created table %s", table_ref.path)
        return table


def validate_records(
    records: list[dict[str, Any]],
    expected_dim: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate each chunk and embedding record."""
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for record in records:
        chunk_id = record.get("chunk_id")
        nct_id = record.get("nct_id")
        text = record.get("chunk_text")
        embedding = record.get("embedding")

        if not chunk_id or not nct_id or not text or not text.strip():
            logger.warning(
                "Rejecting record %s: missing ID, NCT, or text.",
                chunk_id,
            )
            rejected.append({
                "record": record,
                "reason": "Missing required field or empty text",
            })
            continue

        if (
            not isinstance(embedding, (list, tuple))
            or len(embedding) != expected_dim
        ):
            dimension = len(embedding) if embedding else 0
            logger.warning(
                "Rejecting record %s: invalid embedding dimension %s.",
                chunk_id,
                dimension,
            )
            rejected.append({
                "record": record,
                "reason": f"Dimension mismatch (expected {expected_dim})",
            })
            continue

        if any(
            value is None or not math.isfinite(value)
            for value in embedding
        ):
            logger.warning(
                "Rejecting record %s: embedding contains NaN, Inf, or None.",
                chunk_id,
            )
            rejected.append({
                "record": record,
                "reason": "Non-finite values in embedding",
            })
            continue

        valid.append(record)

    return valid, rejected


def get_existing_chunk_ids(
    client: bigquery.Client,
    table_ref: bigquery.TableReference,
) -> set[str]:
    """Fetch existing chunk IDs from BigQuery to prevent duplicate processing."""
    query = (
        f"SELECT chunk_id FROM "
        f"`{table_ref.project}.{table_ref.dataset_id}.{table_ref.table_id}`"
    )
    try:
        query_job = client.query(query, location=settings.bq_location)
        return {row.chunk_id for row in query_job}
    except Exception:
        # Fail closed: do not regenerate embeddings or append duplicates if
        # BigQuery cannot be checked successfully.
        logger.exception("Could not fetch existing chunk IDs; stopping ingestion.")
        raise


def upload_processed_json_to_gcs(filename: str) -> str:
    """Upload a processed local JSON file through gcs_store.write_json()."""
    file_path = settings.processed_dir / filename
    if not file_path.is_file():
        raise FileNotFoundError(f"Processed JSON file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    # write_json accepts a Python object, not a local file path.
    return gcs_store.write_json(filename, data)


def run_ingestion(refresh: bool = False, batch_size: int = 100) -> None:
    """Read trials, create chunks, embed new chunks, store in BigQuery, upload JSON."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    trials_path = settings.processed_dir / "trials.json"
    if not trials_path.is_file():
        logger.error(
            "Source trials file not found at %s. Run fetch_trials.py first.",
            trials_path,
        )
        sys.exit(1)

    with trials_path.open("r", encoding="utf-8") as file:
        trials = json.load(file)

    # 1. Create chunks from the source trials.
    all_chunks = [
        chunk
        for trial in trials
        for chunk in chunk_trial(trial)
    ]
    logger.info("Loaded %s trials -> %s chunks.", len(trials), len(all_chunks))

    client = bigquery.Client(
        project=settings.gcp_project,
        location=settings.bq_location,
    )

    try:
        table = ensure_table_exists(client)
        table_ref = table.reference

        # 2. Skip chunks already stored in BigQuery unless --refresh is explicit.
        if refresh:
            logger.warning(
                "Explicit --refresh flag specified: full table refresh requested."
            )
            chunks_to_process = all_chunks
        else:
            existing_ids = get_existing_chunk_ids(client, table_ref)
            chunks_to_process = [
                chunk for chunk in all_chunks
                if chunk["id"] not in existing_ids
            ]
            skipped_count = len(all_chunks) - len(chunks_to_process)
            logger.info(
                "Duplicate check: %s chunks exist in BigQuery; "
                "%s already present, %s new chunks to embed.",
                len(existing_ids),
                skipped_count,
                len(chunks_to_process),
            )

        valid_records: list[dict[str, Any]] = []

        # 3. Generate embeddings only for chunks not already in BigQuery.
        if chunks_to_process:
            logger.info(
                "Generating embeddings via Vertex AI for %s chunks...",
                len(chunks_to_process),
            )
            chunk_texts = [chunk["text"] for chunk in chunks_to_process]
            vectors: list[list[float]] = []

            for start in range(0, len(chunk_texts), batch_size):
                batch = chunk_texts[start:start + batch_size]
                batch_vectors = embed(batch, task_type="RETRIEVAL_DOCUMENT")

                if len(batch_vectors) != len(batch):
                    raise RuntimeError(
                        "Embedding count does not match batch size; "
                        "stopping before BigQuery insertion."
                    )

                vectors.extend(batch_vectors)
                logger.info(
                    "Embedded %s/%s chunks.",
                    min(start + len(batch), len(chunk_texts)),
                    len(chunk_texts),
                )

            trial_map = {
                trial["nct_id"]: trial
                for trial in trials
                if trial.get("nct_id")
            }
            records: list[dict[str, Any]] = []

            for chunk, vector in zip(chunks_to_process, vectors):
                trial = trial_map.get(chunk["nct_id"], {})
                metadata = {
                    "title": trial.get("title", ""),
                    "status": trial.get("status", ""),
                    "phases": trial.get("phases", []),
                    "conditions": trial.get("conditions", []),
                    "sponsor": trial.get("sponsor"),
                    "study_url": (
                        "https://clinicaltrials.gov/study/"
                        f"{trial.get('nct_id', '')}"
                    ),
                }
                records.append({
                    "chunk_id": chunk["id"],
                    "nct_id": chunk["nct_id"],
                    "chunk_text": chunk["text"],
                    "chunk_type": chunk.get("type", "overview"),
                    "embedding": vector,
                    "metadata_json": json.dumps(
                        metadata,
                        ensure_ascii=False,
                    ),
                })

            # 4. Validate all generated records before insertion.
            valid_records, rejected_records = validate_records(
                records,
                expected_dim=settings.embedding_dim,
            )
            logger.info(
                "Validation: %s valid records, %s rejected records.",
                len(valid_records),
                len(rejected_records),
            )

            if rejected_records:
                logger.warning(
                    "%s records were rejected and will not be inserted.",
                    len(rejected_records),
                )

            if not valid_records:
                logger.error("No valid records to write to BigQuery. Aborting.")
                return
        else:
            logger.info(
                "All chunks already exist in BigQuery. "
                "Skipping embedding generation and insertion."
            )

        # 5. Insert records. Full table refresh happens only with --refresh.
        if valid_records:
            write_disposition = (
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if refresh
                else bigquery.WriteDisposition.WRITE_APPEND
            )
            logger.info(
                "Loading %s chunks into BigQuery `%s.%s.%s`...",
                len(valid_records),
                table_ref.project,
                table_ref.dataset_id,
                table_ref.table_id,
            )
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                write_disposition=write_disposition,
            )
            load_job = client.load_table_from_json(
                valid_records,
                table_ref,
                job_config=job_config,
            )
            load_job.result()
            logger.info(
                "Successfully loaded %s chunks into BigQuery.",
                len(valid_records),
            )
        else:
            logger.info("No new records to insert into BigQuery.")

        # 6. Update local chunks.json cache.
        chunks_metadata = {
            chunk["id"]: {
                "nct_id": chunk["nct_id"],
                "type": chunk.get("type", "overview"),
                "text": chunk["text"],
            }
            for chunk in all_chunks
        }
        chunks_path = settings.processed_dir / "chunks.json"
        with chunks_path.open("w", encoding="utf-8") as file:
            json.dump(chunks_metadata, file, ensure_ascii=False)
        logger.info("Updated local chunks cache at %s.", chunks_path)

        # 7. Upload processed JSON files to GCS using the implemented helper.
        if settings.gcs_bucket:
            for filename in ("trials.json", "chunks.json"):
                try:
                    object_name = upload_processed_json_to_gcs(filename)
                    logger.info("Uploaded %s to GCS: %s", filename, object_name)
                except Exception:
                    logger.exception(
                        "GCS upload failed for %s. BigQuery processing has "
                        "already completed; fix the GCS issue and retry upload.",
                        filename,
                    )
                    raise
        else:
            logger.info("GCS_BUCKET is not configured; skipping GCS uploads.")

        logger.info("Ingestion completed successfully.")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest clinical trials into BigQuery and GCS."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Explicitly truncate and reload all chunks in BigQuery. "
            "May regenerate embeddings and replace existing table rows."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of chunks per embedding batch.",
    )
    args = parser.parse_args()
    run_ingestion(refresh=args.refresh, batch_size=args.batch_size)
