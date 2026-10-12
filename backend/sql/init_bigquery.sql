-- =============================================================================
-- BigQuery Initialization Script for Clinical Trial RAG Vector Search
-- =============================================================================
-- Usage:
-- 1. Replace the dataset name `clinical_trials` or table name `trial_chunks`
--    if configured differently in your backend/.env file.
-- 2. Execute using bq command or BigQuery Console:
--    bq query --use_legacy_sql=false < backend/sql/init_bigquery.sql
-- =============================================================================

-- Create the dataset if it does not already exist
CREATE SCHEMA IF NOT EXISTS `clinical_trials`
OPTIONS (
  description = "Clinical Trial RAG embeddings, chunks, and metadata",
  location = "us-central1"
);

-- Create the trial chunks table
CREATE TABLE IF NOT EXISTS `clinical_trials.trial_chunks` (
  chunk_id STRING NOT NULL OPTIONS(description="Unique identifier for the chunk, e.g. NCT07601178::overview::0"),
  nct_id STRING NOT NULL OPTIONS(description="ClinicalTrials.gov identifier, e.g. NCT07601178"),
  chunk_text STRING NOT NULL OPTIONS(description="Full text of the chunk used for semantic matching"),
  chunk_type STRING OPTIONS(description="Type of chunk: overview, inclusion, exclusion, or publication"),
  embedding ARRAY<FLOAT64> OPTIONS(description="Vector embedding from text-embedding-005 (768 dimensions)"),
  metadata_json STRING OPTIONS(description="JSON serialized trial metadata (title, status, conditions, study URL, etc.)")
)
OPTIONS (
  description = "Stores trial chunk texts and dense vector embeddings for vector search"
);

