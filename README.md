# Clinical Trial RAG (BigQuery Vector Search)

A decision-support system that matches patient clinical cases to recruiting clinical trials from [ClinicalTrials.gov](https://clinicaltrials.gov/) using **BigQuery Vector Search** and **Gemini Flash** eligibility auditing.

---

## 1. Architecture & Workflow

```
[ClinicalTrials.gov API v2]
         │
         ▼
[Trial Ingestion & Normalization] (~500 trials)
         │
         ▼
[Chunking Logic] (~1,688 chunks: overview, inclusion, exclusion, publications)
         │
         ▼
[Vertex AI Embeddings] (text-embedding-005, 768 dimensions)
         │
         ▼
[Google Cloud BigQuery] (`clinical_trials.trial_chunks` table with VECTOR_SEARCH)
         │
         ▼
[Candidate Retrieval & RRF Fusion] (Reciprocal Rank Fusion + NCT deduplication)
         │
         ▼
[Gemini LLM Eligibility Judge] (Verbatim evidence verification & criteria auditing)
         │
         ▼
[Verifier & Verdict Computation] (ELIGIBLE / POSSIBLY_ELIGIBLE / EXCLUDED)
         │
         ▼
[FastAPI Backend] (http://localhost:8000)
         │
         ▼
[React + Vite Frontend] (http://localhost:5173)
```

---

## 2. Why BigQuery Vector Search?

In previous versions, vector search relied on Vertex AI Vector Search (Matching Engine), which required:
- Deploying a dedicated index endpoint (`vdb.vertexai.goog`).
- Provisioning compute nodes (`e2-standard-2`) 24/7.
- Complex VPC peering or public endpoint management.
- Risk of unresolvable endpoints and connection errors.

**BigQuery Vector Search** provides:
- **Serverless & Pay-Per-Query:** No dedicated 24/7 compute nodes or idle costs.
- **Exact Vector Search:** Uses native GoogleSQL `VECTOR_SEARCH()` with exact cosine distance brute force.
- **No Endpoint Deployment:** No need to manage or debug `vdb.vertexai.goog` hostnames.
- **Unified Storage & Search:** Trial chunks, metadata, and embeddings live in the same structured table.

---

## 3. BigQuery Schema

The table `clinical_trials.trial_chunks` is structured as follows:

| Column Name | Type | Description |
|---|---|---|
| `chunk_id` | `STRING` | Unique identifier, e.g. `NCT07601178::overview::0` |
| `nct_id` | `STRING` | ClinicalTrials.gov study identifier |
| `chunk_text` | `STRING` | Clean chunk text for semantic search and context |
| `chunk_type` | `STRING` | `overview`, `inclusion`, `exclusion`, or `publication` |
| `embedding` | `ARRAY<FLOAT64>` | 768-dimensional dense vector (`text-embedding-005`) |
| `metadata_json` | `STRING` | Serialized trial metadata (status, title, conditions, study URL) |

---

## 4. Setup and Local Execution Guide (Windows PowerShell)

### Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- Google Cloud SDK (`gcloud`) installed with Application Default Credentials (ADC) configured.

### Step 1: Authenticate with Google Cloud
Ensure your local environment has Application Default Credentials set for your GCP project:
```powershell
gcloud auth application-default login
gcloud config set project rare-bastion-503107-q3
```

### Step 2: Configure Environment Variables
Verify or edit `backend/.env`:
```env
GCP_PROJECT=rare-bastion-503107-q3
GCP_LOCATION=us-central1
BIGQUERY_DATASET=clinical_trials
BIGQUERY_CHUNKS_TABLE=trial_chunks
BIGQUERY_LOCATION=us-central1
EMBEDDING_MODEL=text-embedding-005
EMBEDDING_DIM=768
GEMINI_MODEL=gemini-2.5-flash
CANDIDATES_TO_RETRIEVE=20
CANDIDATES_TO_JUDGE=6
TOP_K_RESULTS=3
GCS_BUCKET=clinicaltrail_raw
GCS_PREFIX=clinical-trials
```

### Step 3: Install Backend Dependencies
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 4: Initialize BigQuery Dataset & Table
Run the initialization script to ensure the dataset and table exist:
```powershell
python -m ingestion.build_index
```
Alternatively, apply the SQL script via the `bq` CLI:
```powershell
bq query --use_legacy_sql=false < sql/init_bigquery.sql
```

### Step 5: Ingest Trial Chunks and Embeddings into BigQuery
Run the ingestion process:
```powershell
# Safe idempotent ingestion (skips chunks already in BigQuery):
python -m ingestion.ingest

# Or force a full refresh (opt-in):
python -m ingestion.ingest --refresh
```

### Step 6: Verify BigQuery Integrity
Verify that chunks and vectors are properly stored:
```powershell
bq query --use_legacy_sql=false < sql/verify_bigquery.sql
```

### Step 7: Run Unit and Integration Tests
Execute the automated test suite:
```powershell
pytest tests -v
```

### Step 8: Start Backend and Frontend

**Start the FastAPI backend (Terminal 1):**
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Start the React frontend (Terminal 2):**
```powershell
cd frontend
npm install
npm run dev
```

Visit [http://localhost:5173](http://localhost:5173) in your browser.

---

## 5. Troubleshooting & FAQ

### `requests.exceptions.ConnectionError` pointing to `vdb.vertexai.goog`
- **Cause:** Previous code attempted to query the decommissioned Vertex AI Vector Search endpoint.
- **Solution:** Completed! Retrieval is now handled directly by BigQuery `VECTOR_SEARCH()`. Ensure `INDEX_ID` and `INDEX_ENDPOINT_ID` are removed from `.env`.

### `403 Forbidden` / Permission Denied in BigQuery
- **Cause:** GCP user or service account lacks BigQuery permissions.
- **Solution:** Ensure your account has the following IAM roles:
  - `roles/bigquery.dataEditor` or `roles/bigquery.dataViewer`
  - `roles/bigquery.jobUser`

### `400 Location Mismatch`
- **Cause:** The BigQuery dataset location does not match the query job location.
- **Solution:** Set `BIGQUERY_LOCATION=us-central1` (matching `GCP_LOCATION`) in `backend/.env`.

### `Cannot compute cosine distance against zero vector`
- **Cause:** Zero or non-normalized vectors passed to cosine distance calculation.
- **Solution:** Handled automatically by `embeddings.py` (which unit-normalizes all non-zero vectors) and `retriever.py` (which validates dimensions and numeric values prior to query execution).

