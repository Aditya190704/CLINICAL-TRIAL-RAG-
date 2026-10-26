"""BigQuery Vector Search Table and Index Initializer.
# Describes the purpose of this file.

Initializes the BigQuery dataset and trial_chunks table.
# Creates the required BigQuery storage structure.

In BigQuery, exact brute-force vector search requires NO vector index or
deployed endpoint. An optional vector index can be created later via:
`CREATE VECTOR INDEX ...` when table size scales beyond tens of thousands of chunks.
# Explains that vector search can work without an optional vector index.
"""

import logging  # Provides logging functionality to display progress messages.
from google.cloud import bigquery  # Imports the BigQuery client and resource classes.
from google.cloud.exceptions import NotFound  # Handles missing datasets or tables.

from app.config import settings  # Loads GCP project, BigQuery location, dataset, and table settings.

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")  # Configures log message format and INFO level.
logger = logging.getLogger("build_index")  # Creates a logger for this file.


def init_bigquery_resources(create_index: bool = False) -> None:  # Initializes the BigQuery dataset, table, and optional vector index.
    """Initialize BigQuery dataset and trial_chunks table."""  # Documents the function's purpose.

    client = bigquery.Client(project=settings.gcp_project, location=settings.bq_location)  # Connects to BigQuery using configured project and location.
    dataset_ref = bigquery.DatasetReference(settings.gcp_project, settings.bigquery_dataset)  # Creates a reference to the configured dataset.

    # 1. Dataset
    try:
        client.get_dataset(dataset_ref)  # Checks whether the dataset already exists.
        logger.info(f"Dataset '{settings.bigquery_dataset}' already exists in location '{settings.bq_location}'.")  # Logs that the dataset exists.
    except NotFound:
        logger.info(f"Creating dataset '{settings.bigquery_dataset}' in location '{settings.bq_location}'...")  # Logs that the dataset needs to be created.
        ds = bigquery.Dataset(dataset_ref)  # Creates a dataset resource object.
        ds.location = settings.bq_location  # Sets the dataset's Google Cloud location.
        ds.description = "Clinical Trial RAG embeddings, chunks, and metadata"  # Adds a description of the dataset.
        client.create_dataset(ds)  # Creates the dataset in BigQuery.
        logger.info(f"Created dataset '{settings.bigquery_dataset}'.")  # Confirms dataset creation in the logs.

    # 2. Table
    table_ref = dataset_ref.table(settings.bigquery_chunks_table)  # Creates a reference to the trial chunks table.

    schema = [
        bigquery.SchemaField("chunk_id", "STRING", mode="REQUIRED", description="Unique chunk ID"),  # Stores each chunk's unique identifier.
        bigquery.SchemaField("nct_id", "STRING", mode="REQUIRED", description="NCT identifier"),  # Stores the ClinicalTrials.gov trial ID.
        bigquery.SchemaField("chunk_text", "STRING", mode="REQUIRED", description="Text content"),  # Stores the actual text of the chunk.
        bigquery.SchemaField("chunk_type", "STRING", mode="NULLABLE", description="Type of chunk"),  # Stores the chunk category, such as inclusion or exclusion.
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED", description="Dense embedding vector"),  # Stores the embedding as a repeated list of floating-point numbers.
        bigquery.SchemaField("metadata_json", "STRING", mode="NULLABLE", description="JSON trial metadata"),  # Stores additional trial metadata as a JSON-formatted string.
    ]  # Completes the schema definition for the table.

    try:
        table = client.get_table(table_ref)  # Checks whether the table already exists.
        logger.info(f"Table '{settings.bigquery_chunks_table}' already exists.")  # Logs that the table exists.
    except NotFound:
        logger.info(f"Creating table '{settings.bigquery_chunks_table}'...")  # Logs that the table needs to be created.
        table = bigquery.Table(table_ref, schema=schema)  # Defines a new table with the specified schema.
        table.description = "Stores trial chunk texts and dense vector embeddings for vector search"  # Describes the table's purpose.
        table = client.create_table(table)  # Creates the table in BigQuery.
        logger.info(f"Created table '{settings.bigquery_chunks_table}'.")  # Confirms table creation in the logs.

    logger.info("BigQuery resources initialized successfully.")  # Logs that the dataset and table setup is complete.
    logger.info("Exact brute-force vector search is ready without deploying an endpoint.")  # Logs that exact vector search needs no deployed endpoint.

    # 3. Optional Approximate Nearest Neighbor Vector Index (Opt-in)
    if create_index:  # Creates the vector index only when explicitly enabled.
        logger.info("Creating optional BigQuery vector index...")  # Logs the start of vector index creation.

        sql = f"""
        CREATE VECTOR INDEX IF NOT EXISTS trial_chunks_vector_idx
        ON `{table_ref.project}.{table_ref.dataset_id}.{table_ref.table_id}`(embedding)
        OPTIONS(distance_type='COSINE', index_type='IVF');
        """  # Builds SQL to create an optional IVF vector index using cosine distance.

        job = client.query(sql, location=settings.bq_location)  # Submits the vector index creation query to BigQuery.
        job.result()  # Waits for the query job to finish and raises an error if it fails.
        logger.info("BigQuery vector index created.")  # Logs successful vector index creation.


if __name__ == "__main__":  # Checks whether this file is being executed directly.
    init_bigquery_resources(create_index=False)  # Initializes the dataset and table without creating the optional vector index.