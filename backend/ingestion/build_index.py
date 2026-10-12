"""BigQuery Vector Search Table and Index Initializer.

Initializes the BigQuery dataset and trial_chunks table.
In BigQuery, exact brute-force vector search requires NO vector index or
deployed endpoint. An optional vector index can be created later via:
`CREATE VECTOR INDEX ...` when table size scales beyond tens of thousands of chunks.
"""
import logging
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_index")


def init_bigquery_resources(create_index: bool = False) -> None:
    """Initialize BigQuery dataset and trial_chunks table."""
    client = bigquery.Client(project=settings.gcp_project, location=settings.bq_location)
    dataset_ref = bigquery.DatasetReference(settings.gcp_project, settings.bigquery_dataset)

    # 1. Dataset
    try:
        client.get_dataset(dataset_ref)
        logger.info(f"Dataset '{settings.bigquery_dataset}' already exists in location '{settings.bq_location}'.")
    except NotFound:
        logger.info(f"Creating dataset '{settings.bigquery_dataset}' in location '{settings.bq_location}'...")
        ds = bigquery.Dataset(dataset_ref)
        ds.location = settings.bq_location
        ds.description = "Clinical Trial RAG embeddings, chunks, and metadata"
        client.create_dataset(ds)
        logger.info(f"Created dataset '{settings.bigquery_dataset}'.")

    # 2. Table
    table_ref = dataset_ref.table(settings.bigquery_chunks_table)
    schema = [
        bigquery.SchemaField("chunk_id", "STRING", mode="REQUIRED", description="Unique chunk ID"),
        bigquery.SchemaField("nct_id", "STRING", mode="REQUIRED", description="NCT identifier"),
        bigquery.SchemaField("chunk_text", "STRING", mode="REQUIRED", description="Text content"),
        bigquery.SchemaField("chunk_type", "STRING", mode="NULLABLE", description="Type of chunk"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED", description="Dense embedding vector"),
        bigquery.SchemaField("metadata_json", "STRING", mode="NULLABLE", description="JSON trial metadata"),
    ]

    try:
        table = client.get_table(table_ref)
        logger.info(f"Table '{settings.bigquery_chunks_table}' already exists.")
    except NotFound:
        logger.info(f"Creating table '{settings.bigquery_chunks_table}'...")
        table = bigquery.Table(table_ref, schema=schema)
        table.description = "Stores trial chunk texts and dense vector embeddings for vector search"
        table = client.create_table(table)
        logger.info(f"Created table '{settings.bigquery_chunks_table}'.")

    logger.info("BigQuery resources initialized successfully.")
    logger.info("Exact brute-force vector search is ready without deploying an endpoint.")

    # 3. Optional Approximate Nearest Neighbor Vector Index (Opt-in)
    if create_index:
        logger.info("Creating optional BigQuery vector index...")
        sql = f"""
        CREATE VECTOR INDEX IF NOT EXISTS trial_chunks_vector_idx
        ON `{table_ref.project}.{table_ref.dataset_id}.{table_ref.table_id}`(embedding)
        OPTIONS(distance_type='COSINE', index_type='IVF');
        """
        job = client.query(sql, location=settings.bq_location)
        job.result()
        logger.info("BigQuery vector index created.")


if __name__ == "__main__":
    init_bigquery_resources(create_index=False)