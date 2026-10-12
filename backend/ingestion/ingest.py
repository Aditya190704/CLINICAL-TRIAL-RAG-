"""Ingestion script for Clinical Trial RAG.

Chunks trials, generates dense vector embeddings via Vertex AI Embeddings,
and stores chunk records safely in Google Cloud BigQuery.
"""
import argparse
import json
import logging
import math
import sys
from typing import Any

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from app.config import settings
from app.services.embeddings import embed
from app.services import gcs_store
from ingestion.chunker import chunk_trial

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest")


def get_bigquery_table_ref(client: bigquery.Client) -> bigquery.TableReference:
    """Return the BigQuery TableReference for the trial_chunks table."""
    dataset_ref = bigquery.DatasetReference(settings.gcp_project, settings.bigquery_dataset)
    return dataset_ref.table(settings.bigquery_chunks_table)


def ensure_table_exists(client: bigquery.Client) -> bigquery.Table:
    """Ensure the dataset and trial_chunks table exist in BigQuery."""
    dataset_ref = bigquery.DatasetReference(settings.gcp_project, settings.bigquery_dataset)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        logger.info(f"Dataset {settings.bigquery_dataset} not found. Creating in {settings.bq_location}...")
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = settings.bq_location
        client.create_dataset(dataset, exists_ok=True)
        logger.info(f"Dataset {settings.bigquery_dataset} created.")

    table_ref = get_bigquery_table_ref(client)
    schema = [
        bigquery.SchemaField("chunk_id", "STRING", mode="REQUIRED", description="Unique chunk ID"),
        bigquery.SchemaField("nct_id", "STRING", mode="REQUIRED", description="NCT identifier"),
        bigquery.SchemaField("chunk_text", "STRING", mode="REQUIRED", description="Text content"),
        bigquery.SchemaField("chunk_type", "STRING", mode="NULLABLE", description="overview/inclusion/exclusion/publication"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED", description="Dense embedding vector"),
        bigquery.SchemaField("metadata_json", "STRING", mode="NULLABLE", description="JSON trial metadata"),
    ]

    try:
        table = client.get_table(table_ref)
        logger.info(f"Found existing BigQuery table: {table_ref.path}")
        return table
    except NotFound:
        logger.info(f"Creating BigQuery table: {table_ref.path}...")
        table = bigquery.Table(table_ref, schema=schema)
        table = client.create_table(table)
        logger.info(f"Created table {table_ref.path}")
        return table


def validate_records(records: list[dict[str, Any]], expected_dim: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate each chunk and embedding record. Returns (valid_records, rejected_records)."""
    valid = []
    rejected = []

    for r in records:
        chunk_id = r.get("chunk_id")
        nct_id = r.get("nct_id")
        text = r.get("chunk_text")
        embedding = r.get("embedding")

        if not chunk_id or not nct_id or not text or not text.strip():
            logger.warning(f"Rejecting record {chunk_id}: missing ID, NCT, or text.")
            rejected.append({"record": r, "reason": "Missing required field or empty text"})
            continue

        if not isinstance(embedding, (list, tuple)) or len(embedding) != expected_dim:
            logger.warning(f"Rejecting record {chunk_id}: invalid embedding dimension {len(embedding) if embedding else 0}.")
            rejected.append({"record": r, "reason": f"Dimension mismatch (expected {expected_dim})"})
            continue

        if any(v is None or math.isnan(v) or math.isinf(v) for v in embedding):
            logger.warning(f"Rejecting record {chunk_id}: embedding contains NaN, Inf, or None.")
            rejected.append({"record": r, "reason": "Non-finite values in embedding"})
            continue

        valid.append(r)

    return valid, rejected


def get_existing_chunk_ids(client: bigquery.Client, table_ref: bigquery.TableReference) -> set[str]:
    """Fetch existing chunk_ids from the BigQuery table to prevent duplicates."""
    query = f"SELECT chunk_id FROM `{table_ref.project}.{table_ref.dataset_id}.{table_ref.table_id}`"
    try:
        query_job = client.query(query, location=settings.bq_location)
        return {row.chunk_id for row in query_job}
    except Exception as e:
        logger.warning(f"Could not fetch existing chunk IDs ({e}). Assuming table is empty.")
        return set()


def run_ingestion(refresh: bool = False, batch_size: int = 100) -> None:
    """Run ingestion: read trials, chunk, embed, and store in BigQuery."""
    trials_path = settings.processed_dir / "trials.json"
    if not trials_path.exists():
        logger.error(f"Source trials file not found at {trials_path}. Run fetch_trials.py first.")
        sys.exit(1)

    with open(trials_path, encoding="utf-8") as f:
        trials = json.load(f)

    all_chunks = [c for t in trials for c in chunk_trial(t)]
    logger.info(f"Loaded {len(trials)} trials -> {len(all_chunks)} chunks.")

    # Initialize BigQuery client and ensure table exists
    client = bigquery.Client(project=settings.gcp_project, location=settings.bq_location)
    table = ensure_table_exists(client)
    table_ref = table.reference

    # Check existing IDs to prevent redundant embedding generation and duplicates
    existing_ids = set()
    if not refresh:
        existing_ids = get_existing_chunk_ids(client, table_ref)
        chunks_to_process = [c for c in all_chunks if c["id"] not in existing_ids]
        skipped_count = len(all_chunks) - len(chunks_to_process)
        logger.info(f"Duplicate check: {len(existing_ids)} chunks exist in BigQuery. {skipped_count} already present, {len(chunks_to_process)} new chunks to embed.")
    else:
        logger.warning("Explicit --refresh flag specified: Full table refresh requested.")
        chunks_to_process = all_chunks

    if not chunks_to_process:
        logger.info("All chunks already exist in BigQuery. Skipping embedding generation and insert.")
        valid_records = []
    else:
        # Generate embeddings in batches for new chunks only
        logger.info(f"Generating embeddings via Vertex AI for {len(chunks_to_process)} chunks...")
        chunk_texts = [c["text"] for c in chunks_to_process]
        vectors: list[list[float]] = []
        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i : i + batch_size]
            batch_vectors = embed(batch, task_type="RETRIEVAL_DOCUMENT")
            vectors.extend(batch_vectors)
            logger.info(f"Embedded {min(i + batch_size, len(chunk_texts))}/{len(chunk_texts)} chunks.")

        # Prepare trial metadata map
        trial_map = {t["nct_id"]: t for t in trials}

        # Format records for BigQuery
        records = []
        for c, v in zip(chunks_to_process, vectors):
            t = trial_map.get(c["nct_id"], {})
            meta = {
                "title": t.get("title", ""),
                "status": t.get("status", ""),
                "phases": t.get("phases", []),
                "conditions": t.get("conditions", []),
                "sponsor": t.get("sponsor"),
                "study_url": f"https://clinicaltrials.gov/study/{t.get('nct_id', '')}",
            }
            records.append({
                "chunk_id": c["id"],
                "nct_id": c["nct_id"],
                "chunk_text": c["text"],
                "chunk_type": c.get("type", "overview"),
                "embedding": v,
                "metadata_json": json.dumps(meta, ensure_ascii=False),
            })

        # Validate all records before writing
        valid_records, rejected_records = validate_records(records, expected_dim=settings.embedding_dim)
        logger.info(f"Validation: {len(valid_records)} valid records, {len(rejected_records)} rejected records.")

        if not valid_records:
            logger.error("No valid records to write to BigQuery. Aborting insert.")
            return

    # Write records
    if refresh:
        to_write = valid_records
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
    else:
        to_write = valid_records
        write_disposition = bigquery.WriteDisposition.WRITE_APPEND

    if to_write:
        logger.info(f"Loading {len(to_write)} chunks into BigQuery `{table_ref.project}.{table_ref.dataset_id}.{table_ref.table_id}`...")
        job_config = bigquery.LoadJobConfig(
            schema=table.schema,
            write_disposition=write_disposition,
        )
        load_job = client.load_table_from_json(to_write, table_ref, job_config=job_config)
        load_job.result()  # Wait for job to complete
        logger.info(f"Successfully loaded {len(to_write)} chunks into BigQuery.")
    else:
        logger.info("All records already exist in BigQuery. Zero rows inserted (idempotent run).")

    # Update local chunks.json cache for backward compatibility
    meta = {c["id"]: {"nct_id": c["nct_id"], "type": c["type"], "text": c["text"]} for c in all_chunks}
    chunks_path = settings.processed_dir / "chunks.json"
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    logger.info(f"Updated local chunks cache at {chunks_path}.")

    # Upload to GCS if configured
    if settings.gcs_bucket:
        for name in ("trials.json", "chunks.json"):
            uri = gcs_store.upload_file(settings.processed_dir / name, name)
            logger.info(f"Uploaded {name} to GCS: {uri}")

    logger.info("Ingestion completed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest clinical trials into BigQuery.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly truncate and reload all chunks in BigQuery (opt-in full refresh).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for embedding and BigQuery operations.",
    )
    args = parser.parse_args()
    run_ingestion(refresh=args.refresh, batch_size=args.batch_size)