# Clinical Trial RAG Architecture

## Table of Contents

- [Overview](#overview)
- [High-Level Architecture](#high-level-architecture)
- [Components](#components)
- [Main User Flow](#main-user-flow)
- [Business Logic](#business-logic)
- [Data Model](#data-model)
- [Deployment](#deployment)
- [Security](#security)
- [Scalability](#scalability)

## Overview

The application separates offline trial-data preparation from online matching. A bounded ADK layer handles model reasoning. FastAPI and ordinary application code validate inputs, control retrieval, validate evidence, calculate verdicts, and rank results. The API returns preliminary decision support, not a clinical decision.

## High-Level Architecture

```mermaid
flowchart LR
    CTG[ClinicalTrials.gov] --> ING[Ingestion scripts]
    ING --> BQ[(BigQuery trial chunks)]
    ING -. Optional processed files .-> GCS[(Google Cloud Storage)]
    USER[User] --> UI[React and Vite]
    UI --> API[FastAPI]
    API --> SAFE[Validation and urgent screen]
    SAFE --> WF[Bounded workflow]
    WF --> ADK[ADK task agents]
    WF --> RET[Approved retrieval wrapper]
    RET --> BQ
    WF --> STORE[Configured trial store]
    STORE --> WF
    WF --> API
    API --> UI
```

Ingestion writes searchable chunks before runtime. The API applies safety checks before model or retrieval work. Agents receive only task data and have no arbitrary cloud, SQL, shell, filesystem, or network tools.

## Components

| Component | Responsibility |
|---|---|
| React/Vite frontend | Sends matching and chat requests; displays notices, uncertainties, criteria, and citations. |
| FastAPI `main.py` | HTTP boundary, request IDs, safe HTTP error mapping, health and readiness. |
| `pipeline.py` | Length and direct-identifier validation, deterministic urgent screening, workflow entry. |
| `agents/adk_runtime.py` | Creates one ADK `LlmAgent` and ephemeral in-memory session per model task; enforces per-call timeout and deletes the session. |
| `agents/tasks.py` | Focused extraction, criteria-assessment, and follow-up chat agents. |
| `agents/tools.py` | Validated retrieval request and request-local two-call budget around the existing retrieval service. |
| `agents/workflow.py` | Extraction, one deterministic retrieval, candidate validation, serial capped assessment, deterministic verdict and similarity ranking. |
| `services/eligibility_judge.py` | Verifies model quotes and computes conservative verdicts in ordinary code. |
| `services/chat.py` | Retrieves evidence for validated selected trial IDs and returns citations. |
| `services/trial_store.py` | Loads configured processed trial and passage data. |
| `ingestion/` and BigQuery | Fetch, chunk, embed, and store trial records for vector retrieval. |

## Main User Flow

```mermaid
sequenceDiagram
    actor User
    participant UI as React UI
    participant API as FastAPI
    participant Safety as Validation and urgent screen
    participant WF as Matching workflow
    participant ADK as ADK agents
    participant Tool as Bounded retrieval wrapper
    participant BQ as BigQuery
    User->>UI: Submit anonymized case
    UI->>API: POST /api/match
    API->>Safety: Validate length and identifiers
    Safety->>Safety: Check urgent warning phrases
    alt urgent warning found
        Safety-->>API: Notice and empty results
        API-->>UI: Advisory response
    else continue matching
        Safety->>WF: Start workflow
        WF->>ADK: Extract facts and uncertainty
        ADK-->>WF: Pydantic-validated profile
        WF->>WF: Build sanitized deterministic query
        WF->>Tool: One case-grounded query
        Tool->>BQ: Search configured trial chunks
        BQ-->>Tool: Candidate passages
        Tool-->>WF: Candidate list
        loop Each candidate in stable order
            WF->>ADK: Assess one trial
            ADK-->>WF: Criterion evidence
            WF->>WF: Verify quotes and compute verdict
        end
        WF->>WF: Rank by similarity; NCT ID breaks ties
        WF-->>API: MatchResponse
        API-->>UI: Results and disclaimer
    end
```

There is exactly one retrieval query per match request. The same case produces the same sanitized query. Trial assessments run serially; a provider failure stops the loop before any later trial is sent. Assessment failures become API errors and do not produce fallback matches.

## Business Logic

```mermaid
flowchart TD
    CASE[Case text] --> VALID{Length and direct identifiers valid?}
    VALID -->|No| ERROR[Safe validation error]
    VALID -->|Yes| URGENT{Warning phrase not negated?}
    URGENT -->|Yes| NOTICE[Emergency notice and empty results]
    URGENT -->|No| EXTRACT[ADK fact extraction]
    EXTRACT --> SANITIZE[Remove instruction-like clauses]
    SANITIZE --> SEARCH[One deterministic case query]
    SEARCH --> COUNT{Usable candidates}
    COUNT -->|0| EMPTY[Return no candidates and uncertainty]
    COUNT -->|One or more| ORDER[Sort by similarity and NCT ID]
    ORDER --> ASSESS[Serially assess configured candidate cap]
    ASSESS --> VERIFY[Verify source quotes]
    VERIFY --> BLOCK{Verified blocking criterion?}
    BLOCK -->|Yes| EXCLUDED[EXCLUDED for review]
    BLOCK -->|No| POSSIBLE[POSSIBLY_ELIGIBLE]
    EXCLUDED --> RANK[Return in stable similarity order]
    POSSIBLE --> RANK
```

Missing evidence maps to the existing `UNKNOWN` criterion state, shown in the UI as “Could not assess.” It never establishes eligibility. A verified blocker yields `EXCLUDED`; every other assessment remains `POSSIBLY_ELIGIBLE`. An empty result set describes only the search performed and does not mean no suitable trial exists.

The emergency list is a conservative starter placeholder pending clinician approval. Negation handling is intentionally simple; keyword rules can miss emergencies and can produce false positives.

## Data Model

```mermaid
erDiagram
    TRIAL ||--o{ TRIAL_CHUNK : contains
    TRIAL ||--o{ MATCH_RESULT : considered_for
    PATIENT_CASE ||--o{ MATCH_RESULT : produces
    TRIAL {
        string nct_id
        string title
        string status
        string metadata_json
    }
    TRIAL_CHUNK {
        string chunk_id
        string nct_id
        string chunk_type
        string chunk_text
        float_array embedding
    }
    PATIENT_CASE {
        string case_text
        string extracted_profile
    }
    MATCH_RESULT {
        string nct_id
        string verdict
        string criterion_evidence
        float relevance_score
    }
```

`TRIAL` and `TRIAL_CHUNK` reflect the trial data concepts stored in processed files and BigQuery. `PATIENT_CASE` and `MATCH_RESULT` describe transient request/response data; they are not stored server-side by this workflow.

## Deployment

```mermaid
flowchart LR
    BROWSER[Browser] -->|HTTPS| FRONTEND[Frontend host]
    FRONTEND -->|API request| API[FastAPI host]
    API -->|Vector search| BQ[(BigQuery)]
    API -->|Gemini model requests| VERTEX[Gemini Enterprise Agent Platform]
    INGEST[Ingestion job] -->|Write chunks| BQ
    INGEST -. Optional files .-> GCS[(Google Cloud Storage)]
```

The repository has no production hosting manifests. The API currently has no application-level authentication, so keep it local or behind infrastructure-level access controls. Do not expose it publicly or use real patient data until authentication is implemented and reviewed.

## Security

- Length and common direct-identifier checks happen before any model or retrieval call.
- Urgent screening is deterministic and reads the placeholder warning list in `backend/app/urgent_signs.json`. A trigger prevents all matching model and retrieval calls.
- Every agent instruction treats the case, trial records, retrieved passages, and chat question as untrusted data. Inputs are JSON-serialized in a separate user message, not interpolated into instructions.
- ADK agents have no arbitrary tools. Backend-only retrieval validates the query against the case and supported profile facts, filters returned IDs against the configured trial store, and enforces two calls maximum.
- Structured agent outputs are Pydantic-validated. Trial and patient quotes are checked against source text. Verdicts, ranking, and result caps are controlled by application code.
- Each model call uses a fresh in-memory session; it is deleted after that call. No server-side chat history or session persistence is configured.
- Logs avoid patient narratives, extracted facts, queries, prompts, responses, and medical tool payloads. A shared sanitizer logs only request correlation, step, and error category. Framework debug logging is suppressed.
- No authentication or regulatory compliance is implemented or claimed. The emergency list needs qualified clinician review.

## Scalability

- Candidate assessment and final-result caps come from configuration; concurrent assessment is bounded by `ADK_CONCURRENCY`.
- Each model call and retrieval call has a timeout. The matching and chat workflows also have derived overall timeouts capped in code.
- BigQuery provides managed vector storage and search. Monitor query cost and latency when tuning `CANDIDATES_TO_RETRIEVE`.
- Ingestion is independent of request handling and can be scheduled externally, but the repository does not include a scheduler or autoscaling configuration.
- Additional operational needs such as user authentication, access controls, rate limits, monitoring, and deployment automation remain future work.
