-- =============================================================================
-- BigQuery Verification Script for Clinical Trial RAG Vector Search
-- =============================================================================
-- Usage:
-- bq query --use_legacy_sql=false < backend/sql/verify_bigquery.sql
-- =============================================================================

SELECT
  COUNT(*) AS total_chunks,
  COUNT(DISTINCT nct_id) AS total_trials,
  COUNTIF(embedding IS NULL) AS null_embeddings,
  COUNTIF(ARRAY_LENGTH(embedding) != 768) AS invalid_dim_embeddings,
  COUNTIF(chunk_text IS NULL OR LENGTH(TRIM(chunk_text)) = 0) AS empty_chunk_texts,
  COUNTIF(metadata_json IS NULL) AS null_metadata
FROM
  `clinical_trials.trial_chunks`;

-- Sample vector search check to confirm VECTOR_SEARCH syntax and execution
-- Note: Replace @dummy with a 768-dim vector or run test search:
SELECT
  base.chunk_id,
  base.nct_id,
  base.chunk_type,
  distance
FROM VECTOR_SEARCH(
  TABLE `clinical_trials.trial_chunks`,
  'embedding',
  (SELECT 0 AS query_id, embedding AS query_vector FROM `clinical_trials.trial_chunks` LIMIT 1),
  query_column_to_search => 'query_vector',
  top_k => 3,
  distance_type => 'COSINE'
)
LIMIT 3;

