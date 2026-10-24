# Clinical Trial RAG

Clinical Trial RAG helps a clinician or researcher review de-identified patient cases against clinical trial records. It retrieves relevant trial text, assesses criteria against the submitted facts, and presents evidence and uncertainty for human review. It is a research aid; it does not diagnose, recommend treatment, or establish eligibility.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security](#security)
- [Contributing](#contributing)
- [License](#license)

## Overview

The React frontend sends an anonymized case to FastAPI. Deterministic intake checks validate length and common direct identifiers, then screen the reviewable emergency-warning list before any model or retrieval call. Google ADK agents extract supported facts, may propose one bounded search refinement, assess trial criteria, and answer selected-trial follow-up questions. Ordinary application code validates facts and quotations, controls retrieval limits, computes conservative verdicts, and ranks the shortlist.

Every result is preliminary. A qualified clinical team must review the official trial record and confirm any eligibility decision.

## Features

- Search trial chunks stored in BigQuery using Vertex AI embeddings.
- Extract structured facts while reporting missing and conflicting information.
- Screen for configured urgent warning phrases before model or retrieval calls.
- Use one initial retrieval and at most one profile-grounded refinement retrieval.
- Return up to three non-excluded trials and separate verified exclusions.
- Verify model-provided trial and patient quotes before using criterion assessments.
- Review search provenance, evidence coverage, missing facts, and conflicts in an evidence traceability dashboard; download a cited, print-ready report from the browser.
- Return `EXCLUDED` for a verified blocker, `COULD_NOT_ASSESS` when no criterion has supported evidence, and otherwise `POSSIBLY_ELIGIBLE`. This system does not claim likely eligibility because it assesses only a bounded subset of trial criteria.
- Mark criteria that lack enough evidence as `UNKNOWN` (`Could not assess` in the UI).
- Answer follow-up questions from evidence belonging only to validated selected trial IDs.
- Fetch and ingest ClinicalTrials.gov data, with optional PMC enrichment and GCS storage.

## Architecture

1. FastAPI validates the request and screens common direct identifiers.
2. Deterministic emergency screening runs before any model or retrieval work. A trigger returns an emergency notice, empty results, and the advisory disclaimer.
3. An ADK extraction agent returns a Pydantic-validated patient profile and uncertainty signals. Application code verifies facts against the case and removes detected conflicting values from search.
4. Validated diagnoses, key findings, prior treatments, and current medications form the initial retrieval query. Candidate IDs are checked against the configured trial store and deduplicated.
5. If no candidates are found or the best cosine similarity is below `0.35`, one ADK refinement proposal may be requested. The backend accepts it only when all terms occur in validated profile facts and it adds a useful term. The retrieval wrapper enforces at most two calls total.
6. The top candidates are capped at `min(CANDIDATES_TO_JUDGE, 10)`. Independent assessments run concurrently up to `ADK_CONCURRENCY`; outstanding calls are cancelled and cleaned up if the workflow fails or times out. Ordinary code verifies quotes and computes conservative verdicts. Up to three non-excluded trials are ordered by verdict, fewer unresolved criteria, similarity descending, then NCT ID ascending. Excluded trials and their verified blocking reasons appear separately.
7. Follow-up chat validates trial IDs and retrieves evidence only from those selected trials. An ADK chat agent answers from that evidence and reports when it is insufficient.
8. The frontend summarizes validated search facts and criterion coverage across the shortlist. It creates a print-ready HTML report with official study links locally on demand.

ADK agents have no arbitrary shell, filesystem, network, SQL, or Google Cloud tools. Backend code controls the existing retrieval and evidence services. Each model task uses a fresh in-memory ADK session, deleted after the call. ADK session state is not persisted; user chat turns are stored separately in Firestore under the owning session.

See [ARCHITECTURE.md](ARCHITECTURE.md) for Mermaid flowcharts, sequence, data, and deployment diagrams.

## Tech Stack

| Area | Technologies |
|---|---|
| Frontend | React 18, Vite |
| Authentication and persistence | Firebase Authentication, Cloud Firestore |
| API | Python, FastAPI, Pydantic |
| Model orchestration | Google ADK `2.11.0`, Google Gen AI |
| Language model | Gemini 2.5 Flash via Gemini Enterprise Agent Platform |
| Embeddings and retrieval | Vertex AI embeddings, BigQuery `VECTOR_SEARCH` |
| Data sources | ClinicalTrials.gov API v2; optional PMC BioC API |
| Optional object storage | Google Cloud Storage |
| Tests | pytest |

The ADK dependency is pinned to the version installed and inspected for this implementation.

## Prerequisites

- Python 3.11 or later.
- Node.js 18 or later and npm.
- Google Cloud project with Vertex AI and BigQuery access.
- Google Cloud credentials with permission to call the selected models and query/write the configured dataset.
- Firebase project with Email/Password Authentication enabled and Cloud Firestore created.

## Installation

Create the backend environment and install dependencies from `backend/`:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` for your own Google Cloud project and dataset. Authenticate locally with Application Default Credentials:

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

For Firebase, set `FIREBASE_PROJECT_ID` in `backend/.env` to your Firebase project ID. The backend uses Application Default Credentials with Firebase Admin, so the local ADC identity and deployed service account need Firestore access. Copy `frontend/.env.example` to `frontend/.env` and set the Firebase web app values from Firebase Console. Enable **Email/Password** under Authentication sign-in providers. Deploy [`firestore.rules`](firestore.rules); these rules deny direct browser database access because all reads and writes use authenticated FastAPI routes.

Prepare and ingest trial data from `backend/`:

```powershell
python -m ingestion.build_index
python -m ingestion.fetch_trials
python -m ingestion.ingest
```

PMC enrichment is optional:

```powershell
python -m ingestion.fetch_pmc
```

Install frontend dependencies:

```powershell
cd ..\frontend
npm install
```

## Environment Variables

The backend loads `backend/.env` and process environment variables. Never commit real credentials or production secrets.

| Variable | Default/example | Purpose |
|---|---|---|
| `GCP_PROJECT` | Example project in `.env.example` | Google Cloud project ID. |
| `GCP_LOCATION` | `us-central1` | Vertex AI embeddings region and BigQuery location fallback. |
| `GEMINI_LOCATION` | `global` | Gemini serving location. |
| `BIGQUERY_DATASET` | `clinical_trials` | Dataset containing trial chunks. |
| `BIGQUERY_CHUNKS_TABLE` | `trial_chunks` | Table containing chunks and embeddings. |
| `BIGQUERY_LOCATION` | `us-central1` | Optional explicit BigQuery job location. |
| `EMBEDDING_MODEL` | `text-embedding-005` | Embedding model name. |
| `EMBEDDING_DIM` | `768` | Expected vector dimension. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | ADK model used for extraction, criteria assessment, and chat. |
| `CANDIDATES_TO_RETRIEVE` | `40` | BigQuery retrieval chunk limit. |
| `CANDIDATES_TO_JUDGE` | `10` | Assessment count setting, with a hard application cap of 10. |
| `TOP_K_RESULTS` | `3` | Maximum non-excluded shortlist results; hard application cap of 3. |
| `ADK_CONCURRENCY` | `6` | Maximum concurrent criteria assessments. |
| `ADK_TIMEOUT_SECONDS` | `60.0` | Per-agent and retrieval-call timeout; overall matching and chat timeouts are derived from this value and capped in code. |
| `ADK_APP_NAME` | `clinical_trial_matcher` | ADK application label. |
| `GCS_BUCKET` | Empty or configured bucket | Optional bucket for processed JSON. |
| `GCS_PREFIX` | `clinical-trials` | Optional object prefix. |
| `CORS_ORIGINS` | Local Vite origins | Comma-separated allowed frontend origins. |
| `FIREBASE_PROJECT_ID` | Firebase project ID | Firebase Admin token verification and Firestore project. |
| `LOG_LEVEL` | `INFO` | Application log level. Keep framework debug logging disabled. |
| `PROCESSED_DIR` | `<backend>/data/processed` | Optional processed-data path override. |
| `RAW_DIR` | `<backend>/data/raw` | Optional raw-data path override. |

The emergency warning phrases are in [`backend/app/urgent_signs.json`](backend/app/urgent_signs.json). Matching uses one sanitized case query and a stable score order. A retrieval similarity percentage is not an eligibility probability, and close scores should be interpreted as close retrieval matches.

## Usage

Start the API from `backend/`:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
```

Start the frontend in another terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`. The interactive API documentation is at `http://127.0.0.1:8000/docs`.

API endpoints:

- `GET /api/health` — liveness and processed trial count.
- `GET /api/ready` — processed-data readiness.
- `POST /api/match` — matching workflow.
- `POST /api/trials/chat` — selected-trial evidence chat.

Refresh the indexed data when needed:

```powershell
cd backend
python -m ingestion.fetch_trials
python -m ingestion.ingest --refresh
```

`MatchResponse` retains existing fields and adds optional `emergency_notice`, `missing_key_facts`, `conflicting_facts`, `ruled_out_trials`, and `result_message` fields with safe defaults. Criterion `UNKNOWN` remains the criterion-level state; `COULD_NOT_ASSESS` is returned when no trial criterion has supported evidence. An empty shortlist means no suitable non-excluded candidate was found in this search; it does not establish that no suitable trial exists.

## Project Structure

```text
.
|-- backend/
|   |-- app/
|   |   |-- agents/          # ADK runtime, task agents, tools, workflow
|   |   |-- services/        # Auth, Firestore, matching, retrieval, chat, safety
|   |   |-- main.py          # FastAPI routes and middleware
|   |   |-- schemas.py       # Request and response models
|   |   `-- config.py        # Environment-backed settings
|   |-- data/                # Raw and processed trial data
|   |-- ingestion/           # Fetching, chunking, embeddings, ingestion
|   |-- sql/                 # BigQuery setup and verification SQL
|   |-- tests/               # Backend automated tests
|   `-- requirements.txt
|-- frontend/
|   |-- src/
|   |   |-- auth/            # Firebase auth context and sign-in screen
|   |   |-- components/      # Workspace, trial, chat, and UI components
|   |   |-- hooks/           # Session and UI hooks
|   |   |-- api.js           # Authenticated API client
|   |   `-- firebase.js      # Firebase web app initialization
|   |-- .env.example
|   `-- package.json
|-- firebase.json
|-- firestore.rules
|-- ARCHITECTURE.md
`-- README.md
```

## Testing

The backend tests mock model, BigQuery, and Google Cloud calls. Run them from `backend/`:

```powershell
python -m pytest -q
```

The repeatable mocked workflow timing check is `python -m pytest -s tests/test_workflow.py::test_mocked_assessment_latency_improves_with_bounded_concurrency -q`. In one local run, six mocked 30 ms assessment calls took a median **226.3 ms** with concurrency set to 1 and **39.9 ms** with concurrency set to 6. This is a simulated workflow comparison, not a Gemini or BigQuery latency measurement. No live cloud latency or cost measurements were made.

Build the frontend from `frontend/`:

```powershell
npm run build
```

## Deployment

The repository does not include production hosting manifests. Host the frontend on a static web host and FastAPI on an ASGI-compatible service. Configure HTTPS, production CORS origins, secrets, Google Cloud IAM, monitoring, and backups for the chosen platform. Deploy the Firestore rules with:

```powershell
firebase deploy --only firestore:rules
```

Build and serve the frontend from the chosen static host:

```powershell
cd frontend
npm run build
```

Run FastAPI behind the chosen ASGI hosting setup:

```powershell
cd backend
uvicorn app.main:app --host 0.0.0.0 --port <PORT>
```

## Security

- Profile, session, matching, and chat routes require a verified Firebase ID token. Health and readiness routes remain public.
- The backend derives the user UID from the token and scopes Firestore documents to that UID. It also checks that a chat session and selected trial IDs belong to that user/session.
- Application role is fixed server-side to `clinical_technician`; client input cannot assign a different role.
- Firestore rules deny direct browser reads and writes. Server-side Firebase Admin access uses ADC or the deployed service identity.
- A submitted, identifier-screened search is saved to `users/{uid}/sessions/{sessionId}` with its query, server timestamps, title, matched trial IDs, complete structured result (including criteria assessment), and chat turns. This includes health-related data. The sidebar loads sessions newest-updated first; reopening a session restores its query, results, and chat. Deleting a session removes its saved data.
- Search queries are saved only after the API's limited direct-identifier screening. That screening is not comprehensive de-identification; submit only appropriately de-identified cases.
- Token verification skips the per-request revocation lookup to reduce latency. A revoked token may remain valid until normal token expiry.
- The emergency warning list is a placeholder pending qualified clinician review. Phrase screening can miss emergencies and produce false positives.
- Direct-identifier checks are limited and are not comprehensive de-identification. Use only de-identified cases.
- No regulatory compliance, including HIPAA or GDPR compliance, is claimed. Results are advisory and require qualified clinical review against official trial records.
- Request logs avoid patient narratives, extracted facts, search queries, prompts, and model responses.

## Contributing

Create a focused branch, explain behavior or configuration changes in the pull request, and run the backend tests and frontend build before submitting. Keep patient data and credentials out of source files, examples, and logs.

## License

`<LICENSE>` — add the project’s license and license file before distribution.
