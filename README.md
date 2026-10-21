# Clinical Trial RAG

Clinical Trial RAG is a patient-to-trial matching application that helps a clinician or researcher review a de-identified patient case and find recruiting trials that are the closest match. The project combines:

- a FastAPI backend,
- a React frontend,
- Google Cloud BigQuery vector search,
- Vertex AI Gemini models for parsing and eligibility checking,
- an asynchronous Python workflow that ranks candidate trials using relevance and evidence-based review,
- and an evidence-grounded chat endpoint for follow-up questions about selected trials.

The app is not a medical decision engine. It is a decision-support tool that extracts facts from a patient note, retrieves relevant trial chunks, checks eligibility against the trial text, and returns a structured, evidence-based summary.

---

## A. Project Overview

### What the project does
This repository builds a clinical-trial matching system for anonymized patient cases. A user pastes a clinical narrative such as a diagnosis, stage, biomarkers, prior treatments, and comorbidities. The system then:

1. extracts structured facts from the case,
2. finds relevant trials from the registry,
3. compares the patient to trial eligibility text,
4. verifies the model's evidence against the original text,
5. returns a ranked list of trials with verdicts such as ELIGIBLE, POSSIBLY_ELIGIBLE, or EXCLUDED.

### Why it matters
Clinical studies often have strict inclusion and exclusion criteria. A clinician may need to search across many open trials and compare patient facts to those criteria. Doing this manually is slow and error-prone. This project reduces that work by pulling candidate trials and showing the exact trial rule and patient evidence behind each judgment.

### Who can benefit
- Clinical research coordinators
- Trial matching teams
- Oncology or rare-disease study staff
- Data scientists and engineers building retrieval + LLM systems
- Developers learning RAG patterns for regulated domains

### Main features
- Patient case sanitization and PHI rejection
- Structured extraction of age, sex, conditions, findings, and search query
- Dense vector embedding for trial chunks in BigQuery
- Retrieval using GoogleSQL VECTOR_SEARCH
- Candidate ranking with reciprocal rank fusion (RRF)
- Deterministic verdict logic after model assessment
- UI that shows trial evidence, supporting criteria, blocking criteria, and missing information
- Local data ingestion pipeline for ClinicalTrials.gov records and optional PMC abstracts

### Expected outcome
A user can paste a case, review a small set of top trial matches, and understand why a trial is relevant or not, based on the actual wording of the trial criteria and patient note.

---

## B. What, Why, and How

### 1. Patient case intake and privacy filtering
What:
The FastAPI route accepts a patient_case string and rejects names, phone numbers, SSNs, and email addresses.

Why:
This blocks common direct identifiers before the matching workflow makes model or retrieval calls. It is a basic pattern check, not a complete de-identification system.

How:
The `PHI` regex in `backend/app/services/pipeline.py` checks for common identifiers before workflow execution.

Alternative:
A stricter HIPAA-style sanitizer could be used, but it would be more complex and less transparent. The current method is simple and visible in code.

### 2. Patient fact extraction
What:
The `parse_patient` service sends the de-identified case to Gemini and asks for a structured `PatientProfile` object.

Why:
The system needs a canonical representation of age, sex, condition, prior therapy, and key findings to build the search query and later assess trial fit.

How:
`backend/app/services/patient_parser.py` uses `genai.Client(...).models.generate_content()` with a JSON response schema.

Alternative:
A rules-based parser could extract limited facts, but this project chooses an LLM to capture more natural language details with a schema.

### 3. Retrieval of candidate trials
What:
The retrieval layer embeds the patient query and trial text chunks, then performs BigQuery vector search.

Why:
A full trial database is too large for naive string matching. Dense embeddings help find semantically similar chunks quickly.

How:
`retrieve()` calls `embed()` and then `execute_vector_search()` in `backend/app/services/retriever.py`.

Alternative:
Another approach would be keyword search alone, BM25, or a separate vector database. This project chooses BigQuery VECTOR_SEARCH because it keeps storage and search close together and avoids an external vector index service.

### 4. Eligibility evaluation
What:
For each top trial candidate, the system sends the trial eligibility criteria and patient case to Gemini, asking it to label specific inclusion and exclusion criteria as SUPPORTS, BLOCKS, or UNKNOWN.

Why:
The LLM does not decide final eligibility by itself. It provides criterion-level evidence that the application can verify and aggregate.

How:
`backend/app/services/eligibility_judge.py` builds a prompt and validates each returned quote against the original trial text and patient case.

Alternative:
A heuristics-only evaluator would be faster and cheaper, but it would miss nuance and is less transparent. The current project prefers evidence verification to reduce hallucination risk.

### 5. Final verdict and ranking
What:
The final verdict is deterministic: any BLOCKS criterion makes the trial EXCLUDED; otherwise unknowns lead to POSSIBLY_ELIGIBLE; otherwise ELIGIBLE.

Why:
This makes the result explainable and consistent instead of letting the LLM decide the final label.

How:
`compute_verdict()` in `eligibility_judge.py` implements the rules.

Alternative:
A more probabilistic scoring model could be used, but that would be less auditable and harder to explain to end users.

---

## C. Technology Stack

| Technology | What it is | Where it is used | Why it is used | Trade-offs |
|---|---|---|---|---|
| Python | Main backend language | All backend logic | Fast for API and ML integrations | Not as performant as compiled systems for some workloads |
| FastAPI | Python web framework | `backend/app/main.py` | Small API, valid request models, easy async integration | More limited than a full application framework in large enterprise systems |
| React + Vite | Frontend UI framework and dev tooling | `frontend/src/*` | Simple interactive UI with quick iteration | Lightweight but intentionally less opinionated than larger frameworks |
| BigQuery | Google Cloud data warehouse and SQL engine | Retrieval store and vector search | Stores embeddings and allows serverless `VECTOR_SEARCH()` | Requires GCP configuration and permissions |
| Google Gen AI / Gemini | LLM service | Parsing and criteria judging | Understands free-text medical narratives and structured output | Depends on external model availability and token costs |
| Vertex AI Embeddings | Dense embedding model | `backend/app/services/embeddings.py` | Creates semantic vectors for patient queries and trial chunks | Requires GCP and model access |
| Python `asyncio` | Asynchronous workflow coordination | `backend/app/agents/workflow.py` | Runs parsing and retrieval without blocking and bounds concurrent trial judging | The workflow is explicit Python orchestration rather than an ADK agent graph |
| Pydantic | Data validation and schemas | `backend/app/schemas.py` | Enforces input/output shapes and response contracts | Validation errors can need careful handling |
| ClinicalTrials.gov API v2 | Registry data source | `backend/ingestion/fetch_trials.py` | Supplies open recruiting studies | API rate limits and field variability |
| PMC BioC API | Publication abstracts | `backend/ingestion/fetch_pmc.py` | Adds optional publication context for trials | External API availability and rate limits |
| Google Cloud Storage | Optional object storage | `backend/app/services/gcs_store.py`, `backend/app/services/trial_store.py` | Stores processed JSON; the runtime store prefers GCS and can fall back to local files | Not required when using local JSON files |
| pytest | Automated tests | `backend/tests/*` | Checks retrieval, API, and ingestion logic | Not a full end-to-end cloud test suite |

---

## D. Complete Project Architecture

### High-level architecture

```mermaid
flowchart LR
    subgraph Build["Offline data preparation"]
        CTG[ClinicalTrials.gov API] --> FT[fetch_trials.py]
        FT --> TJ[(processed/trials.json)]
        TJ -. optional enrichment .-> PMC[fetch_pmc.py]
        TJ --> CK[chunker.py]
        PMC --> CK
        CK --> ING[ingest.py]
        ING --> EMB_DOC[Vertex AI document embeddings]
        EMB_DOC --> BQ[(BigQuery trial_chunks)]
        ING --> CJ[(processed/chunks.json)]
        ING -. optional upload .-> GCS[(Google Cloud Storage)]
    end

    subgraph Match["Online trial matching"]
        USER[User] --> UI[React App.jsx]
        UI --> APIJS[frontend/src/api.js]
        APIJS -->|POST /api/match| ROUTE[FastAPI main.py]
        ROUTE --> PIPE[pipeline.py\nlength + direct-identifier checks]
        PIPE --> WF[workflow.py\nPython asyncio orchestration]
        WF --> PARSE[patient_parser.py]
        PARSE --> GEM_PARSE[Gemini structured profile]
        WF --> QEMB[embeddings.py\nquery embeddings]
        QEMB --> RET[retriever.py\nBigQuery VECTOR_SEARCH + RRF]
        BQ --> RET
        RET --> CAND[Deduplicated trial candidates]
        CAND --> JUDGE[eligibility_judge.py\nbounded concurrent assessment]
        JUDGE --> GEM_JUDGE[Gemini criterion assessment]
        TJ --> STORE[trial_store.py\ntrial metadata + passages]
        CJ --> STORE
        STORE --> JUDGE
        JUDGE --> RANK[Deterministic verdict + ranking]
        RANK --> SCHEMA[schemas.py\nMatchResponse]
        SCHEMA --> ROUTE
        ROUTE --> UI
    end

    subgraph FollowUp["Follow-up chat"]
        UI --> CHATUI[ChatPanel.jsx]
        CHATUI -->|POST /api/trials/chat| CHATAPI[FastAPI chat route]
        CHATAPI --> CHAT[services/chat.py]
        CHAT --> BQ
        CHAT -. BigQuery has no usable matches .-> CJ
        CHAT --> GEM_CHAT[Gemini evidence-grounded answer]
        GEM_CHAT --> CITES[Citations + answer]
        CITES --> CHATUI
    end
```

The matching workflow has two distinct data paths: ingestion prepares trial text and embeddings before user requests, while the API uses those indexed chunks to find and assess candidates. The chat endpoint is a separate follow-up flow scoped to trials returned by matching; it does not change the eligibility verdict.

The module named `backend/app/agents/workflow.py` currently implements the workflow with Python `asyncio`. `run_adk_workflow()` is retained as a compatibility entry point, but the runtime does not construct ADK `SequentialAgent`/`ParallelAgent` objects or use separate agent state/callback modules.

### Sequence diagram for a matching request

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant API as FastAPI /api/match
    participant Pipeline as services/pipeline.py
    participant Workflow as agents/workflow.py
    participant Parser as patient_parser.py
    participant BigQuery
    participant Judge as eligibility_judge.py
    participant Store as trial_store.py

    User->>Frontend: Paste patient case
    Frontend->>API: POST /api/match
    API->>Pipeline: validate request + scan identifiers
    Pipeline->>Workflow: run_adk_workflow(case)
    Workflow->>Parser: parse_patient(case)
    Parser->>Parser: Gemini structured extraction
    Parser-->>Workflow: PatientProfile
    Workflow->>BigQuery: embed queries + VECTOR_SEARCH
    BigQuery-->>Workflow: candidate chunks and similarity
    Workflow->>Store: load metadata and evidence passages
    Workflow->>Judge: assess candidates with bounded concurrency
    Judge->>Judge: verify quotes; compute verdict per trial
    Judge-->>Workflow: verified criteria + verdicts
    Workflow->>Workflow: rank by verdict, criteria, relevance
    Workflow-->>API: MatchResponse
    API-->>Frontend: ranked matches JSON
    Frontend-->>User: profile, trial cards, criteria, passages
```

### Implemented components and boundaries
- Implemented: ClinicalTrials.gov import, optional PMC enrichment, chunking, embedding ingestion, BigQuery retrieval, patient parsing, eligibility assessment, deterministic ranking, result UI, and selected-trial evidence chat.
- Optional: GCS storage for processed JSON and a BigQuery vector index. BigQuery exact vector search does not require creating the optional index.
- Not shown as implemented: a scheduled ingestion service, authentication/authorization, or an ADK agent graph.

---

## E. Application Source and Data Structure

```text
CLINICAL-TRIAL-RAG/
├── README.md
├── .gitignore
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── agents/
│   │   │   └── workflow.py
│   │   └── services/
│   │       ├── chat.py
│   │       ├── eligibility_judge.py
│   │       ├── embeddings.py
│   │       ├── gcs_store.py
│   │       ├── patient_parser.py
│   │       ├── pipeline.py
│   │       ├── retriever.py
│   │       ├── __init__.py
│   │       └── trial_store.py
│   ├── data/
│   │   └── processed/
│   │       ├── chunks.json
│   │       └── trials.json
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── build_index.py
│   │   ├── chunker.py
│   │   ├── fetch_pmc.py
│   │   ├── fetch_trials.py
│   │   └── ingest.py
│   ├── sql/
│   │   ├── init_bigquery.sql
│   │   └── verify_bigquery.sql
│   └── tests/
│       ├── test_ingest.py
│       ├── test_pipeline.py
│       └── test_retriever.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js
│   └── src/
│       ├── api.js
│       ├── App.jsx
│       ├── config.js
│       ├── main.jsx
│       ├── styles.css
│       └── components/
│           ├── ChatPanel.jsx
│           ├── ProfilePanel.jsx
│           ├── TrialCard.css
│           └── TrialCard.jsx
└── .github/                 # Repository metadata; not part of the runtime path
```

`backend/.env` is intentionally not listed; it is a local configuration file. Copy `.env.example` to create it. `frontend/dist/` is generated build output, not application source. Supporting inventory/structure notes under `backend/` are omitted from this application-source view.

### File responsibilities and how modules connect

#### Root files
- `README.md` — project overview and developer guide.
- `.gitignore` — excludes local environment artifacts and generated files.

#### `backend/app/config.py`
What:
Loads environment settings for GCP, BigQuery, embedding model, and workflow tuning.

Why:
The application needs a single place for runtime config so the same logic can run across local development and cloud environments.

How:
It uses `pydantic-settings` with `backend/.env` support and aliases such as `GCP_PROJECT`, `BIGQUERY_DATASET`, and `ADK_CONCURRENCY`. The latter is a legacy setting name currently used to bound concurrent eligibility checks; the workflow does not create ADK agents.

Dependencies:
- `pydantic`, `pydantic-settings`

Connections:
Used by almost every backend service, including `embeddings.py`, `retriever.py`, `ingest.py`, and `workflow.py`.

Importance:
Without it, the app would not know project IDs, model names, or BigQuery table names.

#### `backend/app/main.py`
What:
Defines the FastAPI app and routes.

Why:
This is the public API layer for the frontend.

How:
It exposes liveness/readiness routes plus `/api/match` and `/api/trials/chat`. It validates request/response schemas, assigns request IDs, applies CORS, and maps service errors to HTTP responses.

Dependencies:
- FastAPI
- `app.schemas`
- `app.services.pipeline`
- `app.services.chat`
- `app.services.trial_store`

Connections:
Used by the React frontend through HTTP calls.

#### `backend/app/schemas.py`
What:
Contains request/response models for patient input and trial results.

Why:
This keeps the API contract clear and validates both incoming data and outgoing responses.

How:
Pydantic models define fields like `patient_case`, `PatientProfile`, `TrialMatch`, and `MatchResponse`.

Dependencies:
- `pydantic`

#### `backend/app/services/pipeline.py`
What:
The matching input-validation and privacy guard before the workflow begins.

Why:
It rejects malformed or overlong cases and common direct identifiers before model or retrieval calls.

How:
It validates the 40–8000 character limit, scans for common email/SSN/phone patterns, then calls `run_adk_workflow()` in `agents/workflow.py`. The function name is retained for compatibility; the implementation is Python orchestration.

#### `backend/app/services/trial_store.py`
What:
Loads processed trial metadata and chunk text from `trials.json` and `chunks.json`.

Why:
The matching workflow needs a fast local lookup for metadata and evidence snippets.

How:
It prefers configured GCS objects and falls back to the configured local processed directory. Cached accessors provide the trial index and chunk text used for result passages and chat fallback.

#### `backend/app/services/embeddings.py`
What:
Generates dense embedding vectors with Gemini embeddings.

Why:
The retrieval layer needs vector representations for both patient queries and trial text chunks.

How:
It calls the Vertex AI embedding model in paced batches, validates dimensions, and normalizes vectors. Ingestion requests document embeddings; matching and chat request query embeddings.

Dependencies:
- `google.genai`
- `numpy`

#### `backend/app/services/retriever.py`
What:
Finds candidate trial chunks using BigQuery `VECTOR_SEARCH`.

Why:
This replaces the older endpoint-based vector search pattern and keeps retrieval within Google Cloud's managed SQL environment.

How:
It builds a parameterized SQL query over the `embedding` column, executes it, and uses RRF to fuse results across multiple queries.

Dependencies:
- `google.cloud.bigquery`
- `app.config`
- `app.services.embeddings`
- `app.services.trial_store`

Connections:
Used by the matching workflow and chat service through `retrieve()` and evidence retrieval.

#### `backend/app/services/patient_parser.py`
What:
Extracts a structured patient profile from the case narrative.

Why:
The app needs a clean, explicit representation of what the patient case states.

How:
Gemini returns a JSON object matching `PatientProfile`, and the code validates the age against the original case text.

#### `backend/app/services/eligibility_judge.py`
What:
An evidence-based eligibility judge that checks whether the patient matches a trial's inclusion/exclusion criteria.

Why:
This is the core "reasoning" step that makes the output explainable rather than just a black-box ranking.

How:
It builds a prompt with the trial text and patient case, checks Gemini output for quote validity, drops hallucinated entries, and computes a final verdict deterministically.

Dependencies:
- `google.genai`
- `app.config`
- `app.schemas`

#### `backend/app/agents/workflow.py`
What:
Coordinates the end-to-end matching request.

Why:
The matching path needs a controlled sequence for parsing and candidate retrieval, then bounded concurrent judging and deterministic ranking.

How:
`_run_workflow_async()` parses the case, retrieves candidates, resolves their metadata and evidence passages, judges candidates concurrently via `asyncio.gather()` and a semaphore, then sorts by verdict, criterion evidence, and relevance. `run_adk_workflow()` wraps this coroutine for the synchronous API route; despite its compatibility name, it does not create ADK agent objects.

Dependencies:
- Python `asyncio`
- `app.services.patient_parser`
- `app.services.retriever`
- `app.services.eligibility_judge`
- `app.services.trial_store`

#### `backend/app/services/chat.py`
What:
Retrieves evidence and answers follow-up questions about selected trials.

Why:
Answers should be grounded in trial passages rather than unsupported model recall.

How:
It validates the question and NCT IDs, retrieves question-relevant chunks from BigQuery for the selected trials, falls back to local processed chunks when needed, and asks Gemini to answer from those passages. It returns citation metadata and does not determine trial eligibility.

#### `backend/ingestion/fetch_trials.py`
What:
Downloads recruiting studies from ClinicalTrials.gov.

Why:
No local data is committed as a full registry; this script builds the dataset needed for matching.

How:
It queries ClinicalTrials.gov API v2 for recruiting studies in the configured therapeutic areas, flattens trial metadata and eligibility text, and writes `backend/data/processed/trials.json`.

#### `backend/ingestion/fetch_pmc.py`
What:
Uses PubMed or PMC identifiers to fetch abstracts from the PMC BioC API.

Why:
Optional publication enrichment improves trial context, though it is not required for the runtime retrieval path.

How:
When run after fetching trial data, it follows available PubMed IDs to PMC BioC abstracts and saves the enrichment back into `trials.json`.

#### `backend/ingestion/chunker.py`
What:
Splits each trial into overview, inclusion, exclusion, and publication chunks.

Why:
Chunking helps vector search match the right evidence segments and keeps search vectors closer to specific criteria.

#### `backend/ingestion/ingest.py`
What:
Loads trial data, chunks, embeds them, validates them, and writes them to BigQuery.

Why:
This is the main ingestion pipeline for local or batch operations.

How:
It reads `trials.json`, chunks each trial, skips existing chunk IDs unless refresh is requested, generates document embeddings, validates records, writes the BigQuery table, and refreshes local `chunks.json`. If configured, it also uploads processed JSON to GCS.

#### `backend/ingestion/build_index.py`
What:
Ensures the BigQuery dataset/table exists and can optionally create a vector index.

Why:
This creates the foundation for the retrieval engine.

#### `backend/sql/init_bigquery.sql`
What:
BigQuery SQL script to initialize schema.

Why:
Useful when running from the `bq` CLI instead of Python.

#### `backend/sql/verify_bigquery.sql`
What:
Checks row counts and confirms the vector-search table structure is valid.

#### `backend/tests/*`
What:
Tests for ingestion validation, retrieval logic, and endpoint compatibility.

Why:
These are the main guardrails for behavior and regressions.

#### `backend/.env.example` and `backend/requirements.txt`
The example file documents local configuration without credentials. The requirements file declares backend API, Google Cloud/model clients, and test dependencies.

#### `frontend/src/App.jsx`
What:
Main React application page and layout.

Why:
This is the user-facing experience for entering a patient case and viewing trial results.

How:
It submits the patient case, handles loading/error/empty states, and renders the profile and ranked trial results. It also opens follow-up chat for the current results.

#### `frontend/src/api.js`
What:
Wrapper around the backend API calls.

Why:
The frontend should not directly know the networking details for each request.

How:
`matchPatient()` sends `POST /api/match`; Vite proxies `/api` requests to the local FastAPI server during development.

#### `frontend/src/main.jsx`, `frontend/src/config.js`, and `frontend/vite.config.js`
`main.jsx` mounts the React app and global styles. `config.js` contains the optional background image URL. `vite.config.js` configures the development server and its `/api` proxy to FastAPI.

#### `frontend/src/components/ChatPanel.jsx`
Submits selected trial IDs, the current case context, and follow-up questions to `POST /api/trials/chat`; it renders answer text, citations, and request errors.

#### `frontend/src/components/TrialCard.jsx`
What:
Displays a single trial match with evidence and citations.

Why:
This makes the output understandable to a user who needs to see trial rules, patient evidence, and summary notes.

#### `frontend/src/components/ProfilePanel.jsx`
What:
Shows the structured patient profile extracted by the backend.

Why:
This lets the user validate the AI's interpretation of their case.

`frontend/src/styles.css`, `frontend/src/components/TrialCard.css`, and `frontend/index.html` provide the UI styling and browser document root.

---

## F. End-to-End Data Flow

### A. Offline trial data pipeline
1. `fetch_trials.py` requests recruiting studies from ClinicalTrials.gov API v2, normalizes their metadata and eligibility criteria, and writes `backend/data/processed/trials.json`.
2. Optionally, `fetch_pmc.py` enriches those trial records with abstracts found through PubMed/PMC references.
3. `chunker.py` turns each record into an overview plus inclusion, exclusion, and available publication chunks. Each chunk has a stable ID, NCT ID, type, and text.
4. `ingest.py` creates chunks, skips chunk IDs already in BigQuery unless a refresh is requested, generates document embeddings, validates vectors and metadata, and writes records to the configured BigQuery `trial_chunks` table.
5. The same ingestion job writes `backend/data/processed/chunks.json` for runtime passage lookup and optionally uploads the processed JSON files to GCS.

`build_index.py` initializes the BigQuery dataset/table and can optionally create a vector index. The SQL scripts provide manual initialization and verification alternatives.

### B. Trial-matching request
1. The user enters a case in `frontend/src/App.jsx`. `frontend/src/api.js` sends `POST /api/match`; the Vite development server proxies `/api` to FastAPI.
2. `backend/app/main.py` validates the request with `MatchRequest`, assigns request metadata, and calls `services/pipeline.py`.
3. `pipeline.run()` enforces the 40–8000 character limit and rejects common direct identifiers (email, US SSN, and phone patterns) before calling any model or retrieval service. This is a basic guardrail, not comprehensive de-identification.
4. `agents/workflow.py` runs `_run_workflow_async()`. `patient_parser.py` asks Gemini for a structured `PatientProfile`; the workflow then sends the profile's search query and a case excerpt to `retriever.py`.
5. `retriever.py` embeds the search strings using `embeddings.py`, runs parameterized BigQuery `VECTOR_SEARCH()` queries, and fuses duplicate trial results using Reciprocal Rank Fusion (RRF).
6. The workflow resolves candidate IDs against `trial_store.py`, which loads processed records from configured GCS when available and otherwise uses local processed JSON. It assesses the top configured candidates concurrently, with concurrency limited by the configured workflow setting.
7. For each candidate, `eligibility_judge.py` asks Gemini to assess trial criteria against the patient case. It checks generated trial and patient quotes against the supplied text, discards unverifiable criterion claims, and returns criterion-level impacts.
8. The workflow computes a deterministic verdict for each trial, orders results by verdict, criterion evidence, then retrieval similarity, and returns a validated `MatchResponse`. `main.py` maps validation and service failures to HTTP responses.
9. `App.jsx`, `ProfilePanel.jsx`, and `TrialCard.jsx` render the profile, trial cards, verdicts, criteria, and retrieved passages. An empty candidate set is returned as a valid response with no matches.

`run_adk_workflow()` is the compatibility name of the workflow entry point. It wraps Python `asyncio`; candidates are judged concurrently using a semaphore, not by ADK agent classes. The request's patient case is passed through the workflow for that request and is not persisted as a server-side chat session.

### C. Selected-trial follow-up chat
1. `ChatPanel.jsx` sends `POST /api/trials/chat` with a question, the currently selected trial IDs, and optional patient-case context.
2. `main.py` validates that the selected IDs exist in the processed trial store and passes the request to `services/chat.py`.
3. The chat service loads chunks only for the selected trials from BigQuery and ranks them against the question. When BigQuery has no usable passages or retrieval fails, it ranks local processed chunks lexically.
4. Gemini receives the question and retrieved trial passages; the response includes citations pointing to ClinicalTrials.gov records. If no usable evidence is found, the service returns an explicit no-evidence answer rather than inventing citations.
5. `ChatPanel.jsx` displays the answer and citations. The chat route is separate from matching and does not revise the eligibility verdict.

---

## G. Core Logic Explained

### 1. `pipeline.run()`
This function is the matching API's input guard. It checks length limits and common direct-identifier patterns before calling `run_adk_workflow()`. The identifier scan is a basic safeguard, not a complete de-identification system.

Important behaviors:
- It checks to prevent SSN, email, and phone patterns.
- It raises a validation error before any GCP model call is made.

### 2. `retrieve()` and `VECTOR_SEARCH`
The retrieval pipeline builds a `list[str]` of queries and calls `embed()`. The returned vectors are validated; then each query vector is sent to a GoogleSQL `VECTOR_SEARCH` call against the `embedding` column in `trial_chunks`.

The user-visible result is a list of `Candidate` objects with:
- `nct_id`
- `rrf` (fused rank score)
- `best_sim` (best cosine similarity)
- `chunk_ids` (evidence list)

This is the main technical choice that sets the project apart from a simple keyword filter: the retrieval step is semantic and uses a vector search index in BigQuery.

### 3. `judge()` and quote verification
The judge has a strict prompt and a strong validation loop. It does not trust the model blindly. Every model-generated criterion quote is checked to ensure:

- it exists in the original eligibility text,
- the patient evidence exists in the patient case when the impact is SUPPORTS or BLOCKS,
- UNKNOWN values are treated without patient evidence,
- invalid or hallucinated statements are dropped and counted.

This is one of the project's biggest design decisions: evidence is verified before the result is shown to the user.

### 4. `compute_verdict()`
This is the deterministic decision logic:

- any BLOCKS result => EXCLUDED
- otherwise, if there are UNKNOWN results or no criteria => POSSIBLY_ELIGIBLE
- otherwise => ELIGIBLE

This ensures that the LLM is a criterion-level auditor, not the final decision-maker.

### 5. Python workflow orchestration
`backend/app/agents/workflow.py` coordinates a workflow that:

1. parses the patient profile,
2. retrieves candidate trials,
3. evaluates trials concurrently with a configured semaphore limit,
4. ranks the final result set.

The `run_adk_workflow()` name is retained for compatibility, but the implementation uses Python `asyncio` and direct service calls rather than ADK `SequentialAgent` or `ParallelAgent` classes.

### 6. Local trial cache and GCS fallback
The code keeps `trials.json` and `chunks.json` in `backend/data/processed/` and can load them from the configured GCS bucket, falling back to local files when GCS objects are unavailable. BigQuery and Vertex AI are still required for cloud vector retrieval and model operations.

---

## H. API Documentation

### Health endpoint
Method: `GET`
Endpoint: `/api/health`

Purpose:
Check whether the API process is responding. Use `/api/ready` to verify that processed trial metadata is available.

Example request:
```http
GET http://localhost:8000/api/health
```

Example response:
```json
{
  "status": "ok",
  "trials_indexed": 500
}
```

Possible status codes:
- `200 OK`

Source:
`backend/app/main.py`

### Match endpoint
Method: `POST`
Endpoint: `/api/match`

Purpose:
Accept a de-identified patient case and return ranked trial matches.

Request body:
```json
{
  "patient_case": "62-year-old woman with newly diagnosed stage IIIB non-small cell lung cancer, EGFR exon 19 deletion positive..."
}
```

Validation rules:
- `patient_case` is required.
- Minimum length is 40 characters.
- Maximum length is 8000 characters.
- A value containing SSN/email/phone patterns is rejected before workflow execution.

Example response:
```json
{
  "patient_profile": {
    "age_years": 62,
    "sex": "FEMALE",
    "primary_conditions": ["non-small cell lung cancer"],
    "comorbidities": [],
    "current_medications": [],
    "prior_treatments": [],
    "key_findings": ["EGFR exon 19 deletion positive", "stage IIIB"],
    "search_query": "EGFR exon 19 deletion positive stage IIIB non-small cell lung cancer"
  },
  "matches": [
    {
      "rank": 1,
      "nct_id": "NCT12345678",
      "title": "Trial title",
      "url": "https://clinicaltrials.gov/study/NCT12345678",
      "status": "RECRUITING",
      "phases": ["PHASE 2"],
      "conditions": ["non-small cell lung cancer"],
      "sponsor": "Example Sponsor",
      "locations": ["Boston, MA"],
      "relevance_score": 0.91,
      "verdict": "ELIGIBLE",
      "summary": "The assessed trial criteria are consistent with the provided case.",
      "criteria": [],
      "dropped_unverified": 0,
      "passages": []
    }
  ],
  "disclaimer": "Research decision-support only. Not medical advice.",
  "latency_seconds": 12.3
}
```

Possible status codes:
- `200 OK` — successful match
- `400 Bad Request` — invalid patient input or PHI detection
- `422 Unprocessable Entity` — request model validation error
- `503 Service Unavailable` — Google Cloud access denied
- `500 Internal Server Error` — unexpected failure

Source:
`backend/app/main.py` and `backend/app/schemas.py`

### Readiness endpoint
**Method:** `GET`

**Endpoint:** `/api/ready`

Unlike `/api/health`, this checks that processed trial metadata can be loaded. It returns `503 Service Unavailable` if no usable trial data is available.

### Selected-trial chat endpoint
**Method:** `POST`

**Endpoint:** `/api/trials/chat`

Purpose:
Answer a follow-up question using passages retrieved from the selected trials, returning citations to the source trial records.

Request body:
```json
{
  "question": "What information is still missing for the age requirement?",
  "trial_ids": ["NCT12345678"],
  "patient_case": "Optional patient-case context",
  "session_id": "optional-client-session-id"
}
```

`trial_ids` must contain known ClinicalTrials.gov IDs (up to 10 per request). `patient_case` and `session_id` are optional; `session_id` is echoed in the response but is not used for server-side persistence. Chat evidence retrieval is scoped to the selected trials.

Response shape:
```json
{
  "answer": "The available trial passages do not specify this requirement.",
  "citations": [
    {
      "nct_id": "NCT12345678",
      "trial_title": "Trial title",
      "section": "INCLUSION",
      "excerpt": "Eligibility passage excerpt",
      "url": "https://clinicaltrials.gov/study/NCT12345678"
    }
  ],
  "missing_info": null,
  "session_id": "optional-client-session-id"
}
```

If no usable trial evidence is retrieved, the service returns an explicit no-evidence answer and an empty citations list. Invalid questions or trial IDs return `400`; request-schema errors return `422`; cloud access failures may return `503`.

Source: `backend/app/main.py`, `backend/app/services/chat.py`, and `backend/app/schemas.py`.

---

## I. Configuration and Environment Variables

The main settings live in `backend/app/config.py`. These values are read from `backend/.env` and can also be provided as environment variables.

| Variable | Default | Required? | Purpose |
|---|---:|---|---|
| `GCP_PROJECT` / `gcp_project` | empty string | Yes for cloud access | Google Cloud project ID |
| `GCP_LOCATION` / `gcp_location` | `us-central1` | Usually yes | Default region for Gemini and BigQuery operations |
| `BIGQUERY_DATASET` / `bigquery_dataset` | `clinical_trials` | Yes for search | Dataset containing trial chunks |
| `BIGQUERY_CHUNKS_TABLE` / `bigquery_chunks_table` | `trial_chunks` | Yes for search | Table with chunk text and embeddings |
| `BIGQUERY_LOCATION` / `bigquery_location` | `None` | Optional | Specific BigQuery location override |
| `EMBEDDING_MODEL` / `embedding_model` | `text-embedding-005` | Yes | Dense embedding model |
| `EMBEDDING_DIM` / `embedding_dim` | `768` | Yes | Vector length for embeddings |
| `GEMINI_MODEL` / `gemini_model` | `gemini-2.5-flash` | Yes | Model used for parsing and judging |
| `GCS_BUCKET` / `gcs_bucket` | empty string | Optional | Enables JSON uploads to GCS |
| `GCS_PREFIX` / `gcs_prefix` | `clinical-trials` | Optional | Prefix used in GCS object names |
| `TOP_K_CHUNKS` / `top_k_chunks` | `20` | Optional | Number of chunk hits per query |
| `CANDIDATES_TO_JUDGE` / `candidates_to_judge` | `6` | Optional | Max candidates sent to the judge |
| `FINAL_RESULTS` / `final_results` | `3` | Optional | Final number of ranked matches |
| `ADK_CONCURRENCY` / `adk_concurrency` | `6` | Optional | Maximum concurrent eligibility checks (legacy setting name) |
| `ADK_TIMEOUT_SECONDS` / `adk_timeout_seconds` | `60.0` | Optional | Reserved configuration; no workflow timeout is currently applied |
| `ADK_APP_NAME` / `adk_app_name` | `clinical_trial_matcher` | Optional | Reserved configuration; no ADK application/session is currently created |

Example `.env` file:
```env
GCP_PROJECT=your-project-id
GCP_LOCATION=us-central1
BIGQUERY_DATASET=clinical_trials
BIGQUERY_CHUNKS_TABLE=trial_chunks
BIGQUERY_LOCATION=us-central1
EMBEDDING_MODEL=text-embedding-005
EMBEDDING_DIM=768
GEMINI_MODEL=gemini-2.5-flash
GCS_BUCKET=
GCS_PREFIX=clinical-trials
TOP_K_CHUNKS=20
CANDIDATES_TO_JUDGE=6
FINAL_RESULTS=3
ADK_CONCURRENCY=6
```

Important note:
This project does not contain any hidden production secrets in the repo. You should not commit real service-account credentials or API keys. Use your local environment or a secure secret-management system instead.

---

## J. Installation and Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- npm
- Google Cloud SDK and Application Default Credentials (ADC)
- BigQuery access to the target project
- Permission to use Gemini and embedding models in Vertex AI

### 1. Clone and open the repo
```powershell
cd C:\path\to\CLINICAL-TRIAL-RAG-
```

### 2. Create a Python virtual environment
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment variables
Create a file named `.env` in the `backend` folder. Use the variables described above.

Example:
```powershell
Set-Content -Path .env -Value @"
GCP_PROJECT=your-project-id
GCP_LOCATION=us-central1
BIGQUERY_DATASET=clinical_trials
BIGQUERY_CHUNKS_TABLE=trial_chunks
BIGQUERY_LOCATION=us-central1
EMBEDDING_MODEL=text-embedding-005
EMBEDDING_DIM=768
GEMINI_MODEL=gemini-2.5-flash
"@
```

### 4. Authenticate to Google Cloud
```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 5. Initialize BigQuery resources
From `backend`:
```powershell
python -m ingestion.build_index
```
Or, if you prefer using the SQL script:
```powershell
bq query --use_legacy_sql=false < sql/init_bigquery.sql
```

### 6. Build or refresh the trial dataset
If you do not already have processed trial files:
```powershell
python -m ingestion.fetch_trials
```
Then, if you want optional PMC enrichment:
```powershell
python -m ingestion.fetch_pmc
```
Then ingest the data into BigQuery:
```powershell
python -m ingestion.ingest
```
Optional force refresh:
```powershell
python -m ingestion.ingest --refresh
```

### 7. Verify the BigQuery table
```powershell
bq query --use_legacy_sql=false < sql/verify_bigquery.sql
```

### 8. Install frontend dependencies
```powershell
cd ..\frontend
npm install
```

### 9. Start the application
Backend:
```powershell
cd ..\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Frontend:
```powershell
cd ..\frontend
npm run dev
```
Then open:
- Frontend: http://localhost:5173
- API: http://localhost:8000

### 10. Run tests
From `backend`:
```powershell
pytest -q
```

Required vs optional steps:
Required:
- install backend dependencies
- configure GCP and BigQuery settings
- create the BigQuery table
- start the backend and frontend

Optional:
- GCS upload
- PMC enrichment
- creating a vector index in BigQuery

---

## K. Alternatives and Design Trade-Offs

| Design choice | Current approach | Why it fits this project | Benefits | Limitations | Alternative |
|---|---|---|---|---|---|
| Retrieval engine | BigQuery `VECTOR_SEARCH()` | Keeps embeddings and metadata in one managed system | Simple operational model, no custom vector service | Requires GCP + BigQuery permissions | Vertex AI Vector Search or a separate vector DB |
| Workflow orchestration | Python `asyncio` with bounded concurrency | Keeps the sequence explicit and limits concurrent eligibility checks | Direct service calls and deterministic flow | Concurrency is managed in application code | An ADK agent graph or a task queue |
| Eligibility logic | Gemini + quote validation + deterministic verdict | Makes results more explainable and auditable | Users can see evidence-backed decisions | Still depends on LLM output quality | Pure rules-based matching or keyword heuristics |
| Data storage | `trials.json` + `chunks.json` + BigQuery table | Local debugging plus cloud search | Simple dev cycle and production search | Duplicate storage of some data | Single source-of-truth database only |
| Frontend architecture | React with direct fetch to `/api/match` | Minimal UI complexity and minimal dependencies | Fast to build and easy to inspect | Less structured than a larger app framework | Next.js or another full-stack framework |

---

## L. Error Handling and Troubleshooting

### Common setup problems
- `ModuleNotFoundError` / missing packages
  - Fix: activate the virtual environment and run `pip install -r requirements.txt`.

- BigQuery access denied
  - Fix: verify the user or service account has `BigQuery Data Viewer` and `BigQuery Job User` roles.

- Project or dataset not found
  - Fix: confirm `GCP_PROJECT`, `BIGQUERY_DATASET`, and location values are set correctly.

- Embedding dimension mismatch
  - Fix: verify `EMBEDDING_DIM=768` and the same value is used in schema creation and query execution.

### API and model failures
- Gemini request fails
  - The judge returns a safe summary and no fabricated eligibility label.

- No structured output from Gemini
  - The project falls back to the deterministic age/sex checks and warns in logs.

- BigQuery vector search query fails
  - `RuntimeError` or `PermissionError` is surfaced to the endpoint with a clear message.

### Network and runtime issues
- Local frontend cannot reach backend
  - Verify the backend is running on port `8000` and the frontend is using the correct API base.

- Local data files missing
  - Re-run the ingestion scripts before testing the match flow.

### Useful debugging steps
- Inspect the backend logs for `Permission denied`, `NotFound`, or `BadRequest` messages.
- Confirm the `.env` file is in `backend/` instead of the repo root.
- Check the `backend/data/processed/` folder for `trials.json` and `chunks.json`.
- Run the test suite to isolate broken logic before modifying the workflow.

---

## M. Security, Privacy, and Reliability

### Existing protections
- PHI regex rejects obvious identifiers before workflow execution.
- The API does not persist patient narratives in a database or server-side session. Matching sends case text to the configured model service; follow-up chat may also send its optional case context to that service.
- The matching route applies the common-identifier scan; the separate chat route validates selected trial IDs and lengths but does not apply that patient-case identifier scan. Avoid sending direct identifiers through either route.
- Structured output schemas limit model output to expected fields.
- Quote verification prevents some hallucinated trial statements from passing through to the UI.
- The API converts low-level exceptions into safe HTTP responses.

### Remaining risks
- Model output is still probabilistic and may be wrong in subtle or edge cases.
- The project uses external cloud services and therefore depends on their availability and access rights.
- The current approach is designed for research support, not direct patient-care automation.
- The local ingestion dataset can go stale if the ClinicalTrials.gov registry changes and the data is not refreshed.

### Recommended improvements
- Add explicit auth for multi-user deployments.
- Add request logging with redaction for patient narrative text.
- Add retry/backoff around external API calls.
- Add audit logs of model prompts and summarized outputs for review.

---

## N. Testing and Code Quality

The repository contains tests in `backend/tests/`.

### Test coverage
- `test_pipeline.py` checks PHI filtering, pipeline integration, and API behavior.
- `test_retriever.py` checks embedding validation, SQL generation, RRF scoring, and BigQuery errors.
- `test_ingest.py` checks validation and duplicate filtering logic.

### Run tests
From the `backend` folder:
```powershell
pytest -q
```

### Observed gaps
- No end-to-end live cloud test against a real BigQuery table or real Gemini model is committed in the repo.
- There are no frontend browser tests.
- There is no dedicated linting or formatting configuration in the repo snapshot.

These are not failures in the project; they are simply current limitations of the test suite.

---

## O. Limitations and Future Improvements

### Verified limitations
- The runtime depends on Google Cloud access and credentials.
- The system is built around the provided trial dataset; it is not a full zero-latency registry system.
- The final verdict is deterministic but still dependent on the quality of model-generated criterion assessments.
- The project is designed as a research-support tool, not a regulated production clinical decision platform.

### Practical future improvements
- Add scheduled re-ingestion from ClinicalTrials.gov.
- Add a user auth layer and role-based access control.
- Add response caching for repeated patient queries.
- Add stronger telemetry and observability for model latency and failure rates.
- Add automated end-to-end tests using a mock or sandbox GCP environment.

---

## P. Quick Reference

### Important commands
```powershell
# backend setup
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# initialize BigQuery resources
python -m ingestion.build_index

# fetch and ingest data
python -m ingestion.fetch_trials
python -m ingestion.fetch_pmc
python -m ingestion.ingest

# run backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# run frontend
cd ..\frontend
npm install
npm run dev

# run tests
cd ..\backend
pytest -q
```

### Main entry points
- Backend API: `backend/app/main.py`
- Pipeline orchestration: `backend/app/services/pipeline.py`
- Retrieval logic: `backend/app/services/retriever.py`
- Eligibility judge: `backend/app/services/eligibility_judge.py`
- Matching workflow: `backend/app/agents/workflow.py` (Python `asyncio`; compatibility entry point named `run_adk_workflow`)
- Frontend entry: `frontend/src/App.jsx`

### Important directories
- `backend/app` — API, schemas, services, and workflow code
- `backend/ingestion` — registry download and embedding ingestion scripts
- `backend/data/processed` — generated trial and chunk cache files
- `backend/tests` — regression tests
- `frontend/src` — React components and API layer

### API base URL
- Backend: http://localhost:8000
- Frontend: http://localhost:5173

### Key configuration variables
- `GCP_PROJECT`
- `GCP_LOCATION`
- `BIGQUERY_DATASET`
- `BIGQUERY_CHUNKS_TABLE`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIM`
- `GEMINI_MODEL`
- `CANDIDATES_TO_JUDGE`
- `FINAL_RESULTS`

### Where to begin when modifying a feature
- Want to change the API contract? Start in `backend/app/schemas.py` and `backend/app/main.py`.
- Want to change retrieval or ranking? Start in `backend/app/services/retriever.py` and `backend/app/agents/workflow.py`.
- Want to change evidence scoring or judge behavior? Start in `backend/app/services/eligibility_judge.py`.
- Want to change the user experience or display? Start in `frontend/src/App.jsx` and `frontend/src/components/*`.
- Want to refresh the underlying trial dataset? Start in `backend/ingestion/`.

---

## Final note
This repository is a research-oriented clinical trial matching system with a clear separation between data ingestion, semantic retrieval, evidence-based eligibility judge logic, and presentation. The code reflects a practical architecture: secure input handling, BigQuery-based vector search, Gemini for structured extraction and assessment, and a frontend designed to show audit-friendly evidence rather than just a single ranked result.
