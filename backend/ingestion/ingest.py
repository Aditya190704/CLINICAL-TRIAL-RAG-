
"""Ingestion script for Clinical Trial RAG.
# Main purpose: prepare clinical trial chunks, generate embeddings, and store the data.

Chunks trials, generates dense vector embeddings via Vertex AI Embeddings,
and stores chunk records in Google Cloud BigQuery. It also updates the local
chunks.json cache and uploads trials.json and chunks.json to GCS when configured.
# Describes the complete ingestion workflow.
"""

from __future__ import annotations  # Allows flexible type annotations, including forward references.

import argparse  # Reads command-line options such as --refresh and --batch-size.
import json  # Reads trial JSON and writes chunk metadata as JSON.
import logging  # Records progress, warnings, and errors.
import math  # Checks whether embedding values are valid finite numbers.
import sys  # Exits the script when required input data is missing.
from typing import Any  # Represents values whose exact data type may vary.

from google.cloud import bigquery  # Provides the BigQuery client and data-loading functions.
from google.cloud.exceptions import NotFound  # Handles missing BigQuery datasets and tables.

from app.config import settings  # Loads project, dataset, table, paths, and embedding configuration.
from app.services import gcs_store  # Provides the helper for uploading JSON data to GCS.
from app.services.embeddings import embed  # Generates numerical embeddings from text.
from ingestion.chunker import chunk_trial  # Splits a trial into overview, inclusion, exclusion, and publication chunks.

logging.basicConfig(
    level=logging.INFO,  # Displays informational messages, warnings, and errors.
    format="%(asctime)s [%(levelname)s] %(message)s",  # Adds timestamps and log levels to messages.
)
logger = logging.getLogger("ingest")  # Creates a logger specifically for this ingestion script.


def get_bigquery_table_ref(client: bigquery.Client) -> bigquery.TableReference:
    """Return the BigQuery TableReference for the trial_chunks table."""
    # Creates a reusable reference to the configured BigQuery table.

    dataset_ref = bigquery.DatasetReference(
        settings.gcp_project,  # Identifies the Google Cloud project.
        settings.bigquery_dataset,  # Identifies the BigQuery dataset.
    )

    return dataset_ref.table(settings.bigquery_chunks_table)  # Returns the configured table reference.


def ensure_table_exists(client: bigquery.Client) -> bigquery.Table:
    """Ensure the dataset and trial_chunks table exist in BigQuery."""
    # Checks for the required dataset and table, creating them if they are missing.

    dataset_ref = bigquery.DatasetReference(
        settings.gcp_project,  # Selects the Google Cloud project.
        settings.bigquery_dataset,  # Selects the dataset that stores trial chunks.
    )

    try:
        client.get_dataset(dataset_ref)  # Checks whether the dataset already exists.
    except NotFound:
        logger.info(
            "Dataset %s not found. Creating in %s...",
            settings.bigquery_dataset,  # Logs the missing dataset name.
            settings.bq_location,  # Logs the location where the dataset will be created.
        )
        dataset = bigquery.Dataset(dataset_ref)  # Creates a dataset resource object.
        dataset.location = settings.bq_location  # Sets the dataset's Google Cloud location.
        client.create_dataset(dataset, exists_ok=True)  # Creates the dataset if it is still missing.
        logger.info("Dataset %s created.", settings.bigquery_dataset)  # Logs successful creation.

    table_ref = get_bigquery_table_ref(client)  # Gets the reference to the target table.

    schema = [
        bigquery.SchemaField(
            "chunk_id", "STRING", mode="REQUIRED",
            description="Unique chunk ID",
        ),  # Stores the unique identifier of each chunk.

        bigquery.SchemaField(
            "nct_id", "STRING", mode="REQUIRED",
            description="NCT identifier",
        ),  # Stores the ClinicalTrials.gov ID of the original trial.

        bigquery.SchemaField(
            "chunk_text", "STRING", mode="REQUIRED",
            description="Text content",
        ),  # Stores the actual text of the chunk.

        bigquery.SchemaField(
            "chunk_type", "STRING", mode="NULLABLE",
            description="overview/inclusion/exclusion/publication",
        ),  # Identifies the category of information contained in the chunk.

        bigquery.SchemaField(
            "embedding", "FLOAT64", mode="REPEATED",
            description="Dense embedding vector",
        ),  # Stores the numerical embedding as a list of floating-point values.

        bigquery.SchemaField(
            "metadata_json", "STRING", mode="NULLABLE",
            description="JSON trial metadata",
        ),  # Stores additional trial details as a JSON-formatted string.
    ]  # Completes the BigQuery table schema.

    try:
        table = client.get_table(table_ref)  # Checks whether the table already exists.
        logger.info("Found existing BigQuery table: %s", table_ref.path)  # Logs the existing table path.
        return table  # Reuses the existing table without creating another one.
    except NotFound:
        logger.info("Creating BigQuery table: %s...", table_ref.path)  # Logs that the table is missing.
        table = bigquery.Table(table_ref, schema=schema)  # Defines a new table with the required columns.
        table = client.create_table(table)  # Creates the table in BigQuery.
        logger.info("Created table %s", table_ref.path)  # Logs successful table creation.
        return table  # Returns the newly created table.


def validate_records(
    records: list[dict[str, Any]],
    expected_dim: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate each chunk and embedding record."""
    # Separates records that are safe to insert from records that fail validation.

    valid: list[dict[str, Any]] = []  # Stores records that pass every validation check.
    rejected: list[dict[str, Any]] = []  # Stores invalid records along with their rejection reasons.

    for record in records:  # Checks each prepared chunk record individually.
        chunk_id = record.get("chunk_id")  # Gets the unique chunk ID.
        nct_id = record.get("nct_id")  # Gets the original clinical trial ID.
        text = record.get("chunk_text")  # Gets the chunk's text.
        embedding = record.get("embedding")  # Gets the chunk's numerical embedding.

        if not chunk_id or not nct_id or not text or not text.strip():
            # Rejects records with missing IDs or empty text.
            logger.warning(
                "Rejecting record %s: missing ID, NCT, or text.",
                chunk_id,  # Identifies the invalid record in the log.
            )
            rejected.append({
                "record": record,  # Keeps the complete record for debugging.
                "reason": "Missing required field or empty text",  # Explains why the record failed.
            })
            continue  # Skips the remaining checks for this record.

        if (
            not isinstance(embedding, (list, tuple))
            or len(embedding) != expected_dim
        ):
            # Ensures the embedding is a list or tuple with the expected number of values.
            dimension = len(embedding) if embedding else 0  # Gets the actual vector length when available.
            logger.warning(
                "Rejecting record %s: invalid embedding dimension %s.",
                chunk_id,  # Identifies the record being rejected.
                dimension,  # Logs the actual embedding dimension.
            )
            rejected.append({
                "record": record,  # Preserves the invalid record for investigation.
                "reason": f"Dimension mismatch (expected {expected_dim})",  # Records the expected dimension.
            })
            continue  # Skips further validation for this record.

        if any(
            value is None or not math.isfinite(value)
            for value in embedding
        ):
            # Rejects embeddings containing None, NaN, positive infinity, or negative infinity.
            logger.warning(
                "Rejecting record %s: embedding contains NaN, Inf, or None.",
                chunk_id,  # Identifies the record with invalid embedding values.
            )
            rejected.append({
                "record": record,  # Preserves the invalid record for investigation.
                "reason": "Non-finite values in embedding",  # Records the validation failure.
            })
            continue  # Skips insertion preparation for this record.

        valid.append(record)  # Adds the record because all validation checks passed.

    return valid, rejected  # Returns valid records and rejected records separately.


def get_existing_chunk_ids(
    client: bigquery.Client,
    table_ref: bigquery.TableReference,
) -> set[str]:
    """Fetch existing chunk IDs from BigQuery to prevent duplicate processing."""
    # Retrieves stored IDs so normal ingestion can skip chunks already in BigQuery.

    query = (
        f"SELECT chunk_id FROM "
        f"`{table_ref.project}.{table_ref.dataset_id}.{table_ref.table_id}`"
    )  # Builds SQL that selects every existing chunk ID from the target table.

    try:
        query_job = client.query(query, location=settings.bq_location)  # Runs the query in the configured BigQuery location.
        return {row.chunk_id for row in query_job}  # Returns the IDs as a set for fast duplicate checks.
    except Exception:
        # Stops ingestion if the existing IDs cannot be checked safely.
        logger.exception("Could not fetch existing chunk IDs; stopping ingestion.")  # Logs the error and traceback.
        raise  # Re-raises the error so ingestion cannot continue with an uncertain duplicate check.


def upload_processed_json_to_gcs(filename: str) -> str:
    """Upload a processed local JSON file through gcs_store.write_json()."""
    # Reads a local processed JSON file and sends its contents to the GCS helper.

    file_path = settings.processed_dir / filename  # Builds the path to the requested processed file.

    if not file_path.is_file():
        # Checks that the local JSON file exists before attempting to upload it.
        raise FileNotFoundError(f"Processed JSON file not found: {file_path}")  # Reports the missing file.

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)  # Parses the JSON file into a Python object.

    # write_json accepts a Python object, not a local file path.
    return gcs_store.write_json(filename, data)  # Uploads the data through the project's GCS helper and returns its object name.


def run_ingestion(refresh: bool = False, batch_size: int = 100) -> None:
    """Read trials, create chunks, embed new chunks, store in BigQuery, upload JSON."""
    # Runs the complete ingestion pipeline, from reading source trials to storing the results.

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")  # Prevents invalid batch sizes.

    trials_path = settings.processed_dir / "trials.json"  # Builds the path to the source trial dataset.

    if not trials_path.is_file():
        # Stops early if fetch_trials.py has not generated the required dataset.
        logger.error(
            "Source trials file not found at %s. Run fetch_trials.py first.",
            trials_path,  # Shows where the missing file was expected.
        )
        sys.exit(1)  # Exits with a failure status because ingestion cannot continue.

    with trials_path.open("r", encoding="utf-8") as file:
        trials = json.load(file)  # Loads all cleaned clinical trial records into memory.

    # 1. Create chunks from the source trials.
    all_chunks = [
        chunk
        for trial in trials  # Processes every trial from trials.json.
        for chunk in chunk_trial(trial)  # Converts each trial into its individual text chunks.
    ]
    logger.info("Loaded %s trials -> %s chunks.", len(trials), len(all_chunks))  # Reports the number of trials and generated chunks.

    client = bigquery.Client(
        project=settings.gcp_project,  # Connects to the configured Google Cloud project.
        location=settings.bq_location,  # Uses the configured BigQuery location.
    )

    try:
        table = ensure_table_exists(client)  # Ensures the required dataset and table are available.
        table_ref = table.reference  # Saves the reference to the target table.

        # 2. Skip chunks already stored in BigQuery unless --refresh is explicit.
        if refresh:
            logger.warning(
                "Explicit --refresh flag specified: full table refresh requested."
            )  # Warns that refresh mode is enabled and existing table data may be replaced.
            chunks_to_process = all_chunks  # Selects every chunk for regeneration and reload.
        else:
            existing_ids = get_existing_chunk_ids(client, table_ref)  # Gets all chunk IDs already stored in BigQuery.
            chunks_to_process = [
                chunk for chunk in all_chunks
                if chunk["id"] not in existing_ids  # Keeps only chunks whose IDs are not already stored.
            ]
            skipped_count = len(all_chunks) - len(chunks_to_process)  # Counts chunks skipped as already present.
            logger.info(
                "Duplicate check: %s chunks exist in BigQuery; "
                "%s already present, %s new chunks to embed.",
                len(existing_ids),  # Reports how many IDs already exist in the table.
                skipped_count,  # Reports how many source chunks will be skipped.
                len(chunks_to_process),  # Reports how many new chunks need embeddings.
            )

        valid_records: list[dict[str, Any]] = []  # Initializes the records that will pass validation.

        # 3. Generate embeddings only for chunks not already in BigQuery.
        if chunks_to_process:
            logger.info(
                "Generating embeddings via Vertex AI for %s chunks...",
                len(chunks_to_process),  # Reports how many chunks require embeddings.
            )
            chunk_texts = [chunk["text"] for chunk in chunks_to_process]  # Extracts the text that Vertex AI will embed.
            vectors: list[list[float]] = []  # Collects generated embedding vectors in chunk order.

            for start in range(0, len(chunk_texts), batch_size):
                # Processes text in batches to control request size and resource usage.
                batch = chunk_texts[start:start + batch_size]  # Selects the next group of text chunks.
                batch_vectors = embed(batch, task_type="RETRIEVAL_DOCUMENT")  # Generates document embeddings for retrieval.

                if len(batch_vectors) != len(batch):
                    # Ensures every input chunk has a corresponding embedding.
                    raise RuntimeError(
                        "Embedding count does not match batch size; "
                        "stopping before BigQuery insertion."
                    )  # Stops before inserting mismatched data.

                vectors.extend(batch_vectors)  # Appends vectors in the same order as their input chunks.
                logger.info(
                    "Embedded %s/%s chunks.",
                    min(start + len(batch), len(chunk_texts)),  # Reports the number of chunks processed so far.
                    len(chunk_texts),  # Reports the total number of chunks requiring embeddings.
                )

            trial_map = {
                trial["nct_id"]: trial
                for trial in trials  # Iterates through the source trial records.
                if trial.get("nct_id")  # Includes only trials with an NCT identifier.
            }  # Creates a lookup from trial ID to its full metadata.

            records: list[dict[str, Any]] = []  # Prepares the BigQuery row records.

            for chunk, vector in zip(chunks_to_process, vectors):
                # Pairs each chunk with its generated embedding.
                trial = trial_map.get(chunk["nct_id"], {})  # Finds the original trial metadata for this chunk.

                metadata = {
                    "title": trial.get("title", ""),  # Stores the trial title.
                    "status": trial.get("status", ""),  # Stores the trial status.
                    "phases": trial.get("phases", []),  # Stores the trial phases.
                    "conditions": trial.get("conditions", []),  # Stores the medical conditions.
                    "sponsor": trial.get("sponsor"),  # Stores the trial sponsor when available.
                    "study_url": (
                        "https://clinicaltrials.gov/study/"
                        f"{trial.get('nct_id', '')}"
                    ),  # Builds the ClinicalTrials.gov page URL for the trial.
                }

                records.append({
                    "chunk_id": chunk["id"],  # Maps the chunk's unique ID to the BigQuery column.
                    "nct_id": chunk["nct_id"],  # Maps the original trial ID to the BigQuery column.
                    "chunk_text": chunk["text"],  # Stores the chunk's searchable text.
                    "chunk_type": chunk.get("type", "overview"),  # Stores the chunk type or defaults to overview.
                    "embedding": vector,  # Stores the numerical vector generated by Vertex AI.
                    "metadata_json": json.dumps(
                        metadata,
                        ensure_ascii=False,  # Preserves non-English characters when serializing metadata.
                    ),
                })  # Adds the complete row matching the BigQuery schema.

            # 4. Validate all generated records before insertion.
            valid_records, rejected_records = validate_records(
                records,
                expected_dim=settings.embedding_dim,  # Requires every embedding to match the configured vector dimension.
            )
            logger.info(
                "Validation: %s valid records, %s rejected records.",
                len(valid_records),  # Reports the number of records that passed validation.
                len(rejected_records),  # Reports the number of records that failed validation.
            )

            if rejected_records:
                logger.warning(
                    "%s records were rejected and will not be inserted.",
                    len(rejected_records),  # Reports how many invalid records will be excluded.
                )

            if not valid_records:
                logger.error("No valid records to write to BigQuery. Aborting.")  # Explains why the load cannot proceed.
                return  # Stops ingestion without inserting any records.
        else:
            logger.info(
                "All chunks already exist in BigQuery. "
                "Skipping embedding generation and insertion."
            )  # Avoids unnecessary embedding requests when there are no new chunks.

        # 5. Insert records. Full table refresh happens only with --refresh.
        if valid_records:
            write_disposition = (
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if refresh
                else bigquery.WriteDisposition.WRITE_APPEND
            )  # Replaces existing table data in refresh mode; otherwise appends new rows.

            logger.info(
                "Loading %s chunks into BigQuery `%s.%s.%s`...",
                len(valid_records),  # Reports how many valid rows will be loaded.
                table_ref.project,  # Identifies the destination project.
                table_ref.dataset_id,  # Identifies the destination dataset.
                table_ref.table_id,  # Identifies the destination table.
            )

            job_config = bigquery.LoadJobConfig(
                schema=table.schema,  # Uses the destination table's schema for the load job.
                write_disposition=write_disposition,  # Configures whether to append or replace table data.
            )

            load_job = client.load_table_from_json(
                valid_records,  # Sends the validated chunk records to BigQuery.
                table_ref,  # Specifies the destination table.
                job_config=job_config,  # Applies the schema and write behavior.
            )

            load_job.result()  # Waits for BigQuery to finish loading the records.
            logger.info(
                "Successfully loaded %s chunks into BigQuery.",
                len(valid_records),  # Reports the number of successfully loaded rows.
            )
        else:
            logger.info("No new records to insert into BigQuery.")  # Logs that there is nothing to load.

        # 6. Update local chunks.json cache.
        chunks_metadata = {
            chunk["id"]: {
                "nct_id": chunk["nct_id"],  # Saves the original trial ID for this chunk.
                "type": chunk.get("type", "overview"),  # Saves the chunk type.
                "text": chunk["text"],  # Saves the chunk text.
            }
            for chunk in all_chunks  # Includes metadata for every generated chunk.
        }  # Creates a dictionary indexed by unique chunk IDs.

        chunks_path = settings.processed_dir / "chunks.json"  # Builds the local cache file path.
        with chunks_path.open("w", encoding="utf-8") as file:
            json.dump(chunks_metadata, file, ensure_ascii=False)  # Writes the chunk metadata and text to JSON.
        logger.info("Updated local chunks cache at %s.", chunks_path)  # Logs where the local cache was saved.

        # 7. Upload processed JSON files to GCS using the implemented helper.
        if settings.gcs_bucket:
            # Runs uploads only when a GCS bucket is configured.
            for filename in ("trials.json", "chunks.json"):
                # Uploads both the original processed trials and the chunk cache.
                try:
                    object_name = upload_processed_json_to_gcs(filename)  # Uploads the JSON file and gets its GCS object name.
                    logger.info("Uploaded %s to GCS: %s", filename, object_name)  # Logs successful upload details.
                except Exception:
                    # Logs upload failures after the BigQuery processing stage.
                    logger.exception(
                        "GCS upload failed for %s. BigQuery processing has "
                        "already completed; fix the GCS issue and retry upload.",
                        filename,  # Identifies which JSON file failed to upload.
                    )
                    raise  # Propagates the failure so the run is not reported as fully successful.
        else:
            logger.info("GCS_BUCKET is not configured; skipping GCS uploads.")  # Explains why GCS uploads were skipped.

        logger.info("Ingestion completed successfully.")  # Reports successful completion of the workflow.
    finally:
        client.close()  # Releases the BigQuery client resources even if ingestion fails.


if __name__ == "__main__":  # Runs the command-line interface only when this file is executed directly.
    parser = argparse.ArgumentParser(
        description="Ingest clinical trials into BigQuery and GCS."
    )  # Creates a parser for command-line options.

    parser.add_argument(
        "--refresh",
        action="store_true",  # Makes refresh a flag that defaults to False.
        help=(
            "Explicitly truncate and reload all chunks in BigQuery. "
            "May regenerate embeddings and replace existing table rows."
        ),  # Warns users that refresh can replace existing BigQuery data.
    )

    parser.add_argument(
        "--batch-size",
        type=int,  # Converts the supplied batch-size value into an integer.
        default=100,  # Uses 100 chunks per embedding request batch unless overridden.
        help="Number of chunks per embedding batch.",  # Describes the option.
    )

    args = parser.parse_args()  # Reads the command-line arguments supplied by the user.
    run_ingestion(refresh=args.refresh, batch_size=args.batch_size)  # Starts ingestion using the selected options.
