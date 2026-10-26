# Online Clinical Trial Matching Architecture

This document describes the online behavior implemented by the checked-out source, not a proposed design. The architecture diagram is in [ONLINE_ARCHITECTURE.mmd](./ONLINE_ARCHITECTURE.mmd), and the code-to-arrow evidence is in [ARCHITECTURE_EVIDENCE.md](./ARCHITECTURE_EVIDENCE.md).

## Runtime at a glance

- **Frontend:** React/Vite. Firebase Authentication is used in the browser. The frontend calls FastAPI with the current Firebase ID token; browser code does not directly access Firestore.
- **API:** FastAPI exposes authentication/profile, session, matching, chat, health, and readiness routes. `require_firebase_user` protects profile, session, match, and chat routes.
- **Identity and user data:** Firebase Admin verifies tokens and accesses Cloud Firestore. User documents, sessions, match results, and chat messages are scoped under the verified UID.
- **Trial corpus:** `trial_store` loads processed `trials.json` and `chunks.json` from configured GCS when available, with local processed-file fallback. Results are cached in-process. This is separate from matching vector retrieval.
- **Matching retrieval:** Vertex AI generates query embeddings; BigQuery `VECTOR_SEARCH` searches the configured trial-chunk table. Multiple query result lists are fused with application-level RRF and deduplicated.
- **Model work:** Focused Google ADK `LlmAgent` tasks call Gemini for patient fact extraction, optional query refinement, per-trial criteria assessment, and follow-up chat. Application code—not ADK multi-agent orchestration—sequences and bounds these tasks.
- **Online GCS writes:** None are performed by the matching, chat, or user-data request paths described here. The GCS helper module has read/write helpers, but the online data loader uses its own read implementation and the online session/result/chat persistence uses Firestore.

## Flow A — Authentication and session loading

1. `main.jsx` mounts `AuthProvider` around `App`.
2. `AuthScreen` supports email/password sign-in, account creation, and password-reset requests through Firebase Authentication. The browser configuration comes from `VITE_FIREBASE_*` variables.
3. On sign-in, Firebase's `onAuthStateChanged` callback obtains the user's ID token and calls `GET /api/auth/profile`. The API client adds the current user's bearer token to API requests. On signup, the frontend creates the Firebase account, updates its display name, refreshes the ID token, then calls `POST /api/auth/profile` with `display_name`.
4. FastAPI's `require_firebase_user` requires a bearer credential and calls Firebase Admin `verify_id_token`. It derives a constrained UID from the verified `uid`/`sub` claim; email and display name are taken from verified claims. Invalid/absent credentials return 401; missing server Firebase configuration returns 503. Revocation checking is explicitly disabled (`check_revoked=False`).
5. `GET /api/auth/profile` calls `get_or_create_profile`; profile records live at `users/{uid}`. The role returned by the service is fixed to `clinical_technician`, rather than trusted from stored/client role data. Signup's `POST` initializes/updates controlled profile fields.
6. Once authenticated, `useSessionManager` calls `GET /api/sessions`. If the list is empty, it calls `POST /api/sessions`, then loads the first session with `GET /api/sessions/{session_id}`. Session documents are under `users/{uid}/sessions/{session_id}`; chat messages are subdocuments under `messages`.
7. The session hook maps the API's `searchQuery`, saved result (`data`), and `chatHistory` into React state. The workspace shows session history and the active session. Opening another session fetches its detail. The browser also clears legacy local storage before loading the authenticated user's sessions.

Session operations implemented by the API include:

| Method and route | Purpose |
|---|---|
| `GET /api/auth/profile` | Get or initialize the verified user's profile. |
| `POST /api/auth/profile` | Initialize/update profile after signup; body has `display_name`. |
| `GET /api/sessions` | List the verified user's sessions and compact result summaries. |
| `POST /api/sessions` | Create a session; optional/default title is “New Patient Session”. |
| `GET /api/sessions/{session_id}` | Load an owned session, full saved result, and reconstructed chat history. |
| `PATCH /api/sessions/{session_id}` | Rename an owned session. |
| `DELETE /api/sessions/{session_id}` | Delete an owned session and its message documents. |
| `DELETE /api/sessions` | Delete all of the verified user's sessions. |
| `DELETE /api/sessions/{session_id}/messages` | Clear an owned session's chat messages. |
| `DELETE /api/sessions/{session_id}/result` | Clear the saved query/result state of an owned session. |

Session ownership is enforced by constructing Firestore document references beneath the verified UID, then returning “not accessible” when the session does not exist at that path. These API calls do not use a client-provided UID.

## Flow B — Online clinical trial matching

### Request and persistence order

1. The technician enters an anonymized narrative in the React workspace. `App.jsx` trims it, requires at least 40 characters in the UI, and submits only when a session is active. If that session already has a result, the UI creates a new session for this search.
2. `matchPatient(patientCase, sessionId)` sends `POST /api/match` with JSON `{ "patient_case": ..., "session_id": ... }`. The API request helper attaches the current Firebase bearer token.
3. FastAPI validates the `MatchRequest` (40–8,000 non-whitespace characters; optional session ID up to 128 characters) and runs `require_firebase_user`.
4. The route calls `pipeline.validate_case` **before durable storage**. This checks bounds and possible direct identifiers using email, US SSN, and phone-number patterns. It is not a general de-identification detector.
5. The route then checks that a supplied session belongs to the verified user, or creates one when `session_id` is absent. It writes the validated narrative to that session's `searchQuery`, sets status to `searching`, and clears prior matched IDs/result summary. Thus the narrative is durably saved **before urgent-warning screening**.
6. `pipeline.run_async` validates the case again, then runs deterministic urgent-sign screening from `backend/app/urgent_signs.json`. If a configured warning phrase is found without the implemented simple negation patterns, matching stops and returns an emergency notice with no matches and `patient_profile.search_query = "Search not performed"`. The route still saves this response and returns it normally. This branch is not a diagnosis or comprehensive emergency detector.
7. Otherwise, `workflow.run_workflow_async` runs under a workflow timeout. It removes recognized instruction-like clauses and invokes the structured `extract_patient` ADK task. `validate_extracted_profile` validates age, sex, and extracted fact strings against the case; unsupported values are discarded. Application code derives missing facts and supported age/stage conflicts. For assessment, mentions of conflicting values are removed from the case.

### Retrieval, assessment, and ranking order

8. Application code builds up to two grounded initial queries: condition-focused and detail-focused (findings, prior treatments, medications); duplicates and empty queries are removed. Query construction and `safe_search_query` constrain terms to the sanitized narrative/profile. `ApprovedTrialRetrieval.search` rechecks grounding and allows at most two calls per request.
9. `retriever.retrieve` embeds the query list using Vertex AI's Gen AI client with `vertexai=True`, model default `text-embedding-005`, task type `RETRIEVAL_QUERY`, and configured output dimensionality (default 768). The embedding client is configured using `GCP_PROJECT` and `GCP_LOCATION`. These are source defaults; environment settings may override them.
10. The application issues a parameterized BigQuery GoogleSQL `VECTOR_SEARCH` against `{GCP_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_CHUNKS_TABLE}` (defaults `clinical_trials.trial_chunks`), searching the `embedding` column with cosine distance and default `CANDIDATES_TO_RETRIEVE=40` per query. This is BigQuery vector retrieval, not Vertex AI Vector Search. The source does not establish whether a BigQuery vector index is configured or whether the deployed query executes in indexed or brute-force mode.
11. BigQuery rows are grouped by query. `fuse_and_deduplicate` accumulates Reciprocal Rank Fusion scores (`1 / (60 + rank)` once per trial per query), keeps the best cosine similarity (`max(0, 1 - distance)`, clamped to 1), gathers chunk IDs, and flags instruction-like chunks. Workflow candidate filtering removes invalid/missing metadata IDs, duplicate NCT IDs, flagged candidates, and trial records containing instruction-like text. The workflow's dedupe/sort then orders candidates by best similarity and NCT ID; RRF has already ordered the retriever's original output but is not used as the workflow's later sort key.
12. Trial metadata is loaded separately through `trial_store.trials()` and cached. `trials.json` supplies fields such as eligibility text, title, status, age/sex metadata, sponsor, phases, and locations. Result passages are assembled separately from cached `chunks.json` via candidate chunk IDs. If configured, the data loader tries GCS first and falls back to local processed JSON; it does not use Firestore for the trial corpus.
13. The workflow assesses at most `CANDIDATES_TO_JUDGE` (default 10, hard cap 20). Per-trial `assess_trial` Gemini tasks are independent. Application code schedules them concurrently with `asyncio.gather` and gates active assessments with `ADK_CONCURRENCY` (default 6). They are not a `ParallelAgent`.
14. A refinement proposal is started only if no initial candidates exist or the top similarity is below `0.35`. Its model call runs concurrently with assessment of the initial shortlist. It can result in at most one second retrieval call, and its proposed query must be profile-grounded and useful/different. A failure in this optional branch is logged and initial results are retained. If refined candidates add trials, only missing assessments are run; this second assessment batch follows the initial batch.
15. For each judge output, `verify_judge_output` accepts a criterion quote only when its normalized text is present in the trial's supplied eligibility text. Unsupported or non-lexically-verifiable patient evidence changes a non-`UNKNOWN` impact to `UNKNOWN`; metastatic criteria also require explicit metastatic evidence. Separate deterministic structured age/sex checks can add criteria. The patient-evidence check is lexical support, not semantic entailment. `compute_verdict` derives the preliminary label in application code: any `BLOCKS` => `EXCLUDED`; no `SUPPORTS` and no blocker => `COULD_NOT_ASSESS`; otherwise => `POSSIBLY_ELIGIBLE`. The judge's returned summary is not used for the API match summary; workflow code supplies a generic summary based on the computed verdict. The model's own verdict is not authoritative.
16. Results sort by verdict priority, then unresolved criterion count, then best similarity, then NCT ID. Excluded candidates are listed in `ruled_out_trials` when a verified blocker exists. Only non-excluded candidates are returned in `matches`, capped by `TOP_K_RESULTS` (default 3). An empty shortlist yields a search-specific `result_message`. `relevance_score` is retrieval similarity, not eligibility probability. The backend's current `compute_verdict` does not produce `ELIGIBLE`, despite that value being allowed by the response schema.

### Result persistence and frontend rendering

17. Before returning from `/api/match`, the route stores the full JSON `MatchResponse` as `resultSummary`, writes the returned match NCT IDs to `matchedTrialIds`, and updates session status to `matched`. On a failed search after the query was saved, `mark_search_failed` sets status to `failed`. The response returned to the browser then adds `session_id`; because this copy occurs after the Firestore save, the saved response's `session_id` remains the pipeline default (`null`).
18. `MatchResponse` contains `patient_profile`, `matches`, `disclaimer`, `latency_seconds`, optional `emergency_notice`, `missing_key_facts`, `conflicting_facts`, `ruled_out_trials`, and `result_message`, plus `session_id` when returned by the route. Each match includes metadata, `relevance_score`, verdict, summary, criteria, dropped-unverified count, and retrieved passages.
19. The frontend updates the active React session with the returned result. `ResultsOverview`, `TrialTabs`, `TrialDetailView`, `ClinicalAssessmentPage`, `CriteriaSection`, `PassagesSection`, and `PatientProfileCard` render summaries, verdicts, similarity, profile, missing/conflicting facts, criteria evidence, and source passages. These components are rendering client state; they do not independently call matching APIs.

### Conditional behavior and errors

- Global FastAPI request-schema failures return 422 with field-level error descriptors and a request ID.
- Invalid case length or detected direct identifier returns 400 before the case is persisted. A foreign/nonexistent session returns 403.
- Urgent-warning screening is an early successful matching response (empty matches and notice), not an error.
- Extraction, retrieval, assessment, and workflow timeout failures become `WorkflowError` responses; the route preserves its configured status code. BigQuery permission failures map to 503. Session storage failures map to 503; uncompleted searches are marked `failed` where possible.
- `/api/health` is unauthenticated liveness plus a best-effort processed-trial count. `/api/ready` checks for available processed trial metadata and can return 503. Neither endpoint verifies BigQuery vector search or model availability. The frontend catches health request errors and represents the backend as offline.
- Request middleware assigns/propagates `X-Request-ID`, records status and duration, and avoids logging request bodies. Safe service error logging records error categories rather than patient text.

## Flow C — Follow-up chat about matched trials

1. `ChatDrawer` sends the question, current shortlist trial IDs, session ID, and a generated message ID through `askTrialQuestion`. `api.js` posts `{ question, trial_ids, session_id, message_id }` to `POST /api/trials/chat`. Although the frontend helper accepts `patientCase` and the schema has an optional `patient_case`, `api.js` does not include it in the request body, the route ignores it, and chat does not load it from Firestore.
2. FastAPI requires a verified Firebase user, a non-empty saved session ID, and session ownership. It checks every requested ID against that session's saved `matchedTrialIds`; a foreign trial or session returns 403. The frontend currently supplies all returned matches, not only the currently active trial tab.
3. The route uses `message_id` for idempotency: if an assistant turn with that ID is already in the session, its saved answer/citations are returned without another model call.
4. `chat_answer` normalizes the question and NCT IDs, validates that all IDs exist in the trial metadata store, and retrieves only evidence for those IDs. It first embeds the question with Vertex AI and issues parameterized SQL against the configured BigQuery chunks table restricted by `nct_id IN UNNEST(@trial_ids)`. This chat path does **not** call BigQuery `VECTOR_SEARCH`; it computes cosine similarity in Python over returned rows.
5. If BigQuery yields no usable evidence **or retrieval raises an exception**, the service logs a sanitized category and searches local cached `chunks.json` with lexical overlap scoring. It ranks/deduplicates evidence and caps selection at four passages per trial and twelve total. Content is filtered again to selected IDs and instruction-like clauses are removed. If no usable evidence remains, the service returns a non-model no-evidence response and no citations.
6. With evidence, `answer_trial_question` runs a structured ADK/Gemini task using the question and selected-trial passages. The generated answer is constrained by the task prompt but is not independently checked for factual entailment, quotation accuracy, or citation consistency. Citation objects are assembled by application code from the retrieved passages, trial metadata, and ClinicalTrials.gov URLs; the model does not generate the citation list.
7. The route stores the question and answer in a Firestore batch under `users/{uid}/sessions/{session_id}/messages`, using `{message_id}_user` and `{message_id}_assistant` document IDs, and updates the session timestamp. It returns `ChatResponse` with answer, citations, `missing_info`, and session ID. The UI appends the returned turn and renders answer text and citation links. On later session loading, the backend reconstructs chat history from those message documents.

Chat errors include schema/empty input 422, missing session 400, inaccessible session/trial IDs 403, invalid question/trial data 400, and service errors mapped to 500/503 by the route. Unlike the matching workflow, the chat route does not accept a patient case as model context.

## Data services and offline boundary

| Service | Online role confirmed by source |
|---|---|
| Firebase Authentication | Browser sign-in/sign-up/password-reset; produces ID tokens. |
| Firebase Admin Auth | Verifies bearer ID tokens and derives UID. Revocation lookup is not performed per request. |
| Cloud Firestore | Server-side user profiles, sessions, saved query/result, matched trial IDs, and chat turns. |
| Vertex AI through Google Gen AI SDK | Generates query embeddings; source default model is `text-embedding-005`, configured project/region and 768 dimensions. |
| BigQuery | Matching uses `VECTOR_SEARCH` on `embedding`; chat filters chunk rows by selected NCT IDs and scores embeddings in Python. Source defaults are dataset `clinical_trials`, table `trial_chunks`. |
| Gemini through Google Gen AI SDK / Google ADK | Structured task calls; source defaults are `gemini-2.5-flash`, `GEMINI_LOCATION=global`, and the configured ADK timeout. |
| Google Cloud Storage | Optional source of processed trial/chunk JSON via `trial_store`; configured GCS reads fall back to local files. No online matching/chat persistence writes to GCS are called. |
| Local processed JSON | Fallback and alternate data source for trial metadata/chunks under `PROCESSED_DIR` (default backend processed data directory). |

Index construction, ingestion, and GCS uploads are outside the online request workflow and are not represented as request-time steps. The online code depends on the processed BigQuery chunk table and processed trial/chunk JSON being available.

## Limitations and unverified deployment facts

- `config.py` supplies defaults but allows environment overrides. The deployed values, actual cloud project, IAM grants, Firestore database, GCS bucket contents, BigQuery table contents/index configuration, and live model availability cannot be proven from source. No `.env` or credentials were inspected.
- The online implementation includes simple regex direct-identifier checks, phrase-based urgent screening, and lexical evidence checks. These should not be described as comprehensive de-identification, emergency diagnosis, semantic entailment, or clinical eligibility validation.
- BigQuery is the confirmed vector search backend for matching. Vertex AI is the embedding provider, not a separate Vertex AI Vector Search endpoint.
- Google ADK constructs a request-scoped in-memory session and a task-specific `LlmAgent`/`Runner` for each model task, then deletes that session. Application code orchestrates task ordering and parallelism; there is no `SequentialAgent` or `ParallelAgent` implementation in the inspected online path.
- The follow-up answer is generated from selected-trial evidence, but the answer text itself receives no deterministic evidence/quote verification. Citation metadata is constructed from retrieved evidence after the model call.
- `ResultsOverview.jsx` counts “Requires Clinical Review” only for `ELIGIBLE`/`LIKELY ELIGIBLE`; the backend currently returns `POSSIBLY_ELIGIBLE`, `COULD_NOT_ASSESS`, or excluded trials outside `matches`. This makes that UI metric zero for current backend response labels.
- `MatchResponse` permits the label `ELIGIBLE`; the current verdict function never returns it. The current ranking priority includes it but does not change the verdict behavior.
- Existing `ARCHITECTURE.md` and `README.md` broadly agree on the major services, Firestore persistence, bounded refinement, and verdict safeguards. The architecture wording that groups “BigQuery and Vertex AI” as storing/searching vectors is imprecise: inspected code places vector retrieval in BigQuery and embeddings in Vertex AI. The README's “Autonomous agents” heading also needs qualification: the inspected path uses bounded, request-scoped structured ADK task agents without exposed tools; application code orchestrates their calls. The source-specific distinctions above supersede those broad labels.

## Source inventory

The exact source files inspected for this architecture are listed in [ARCHITECTURE_EVIDENCE.md](./ARCHITECTURE_EVIDENCE.md), including the frontend entry/auth/session/results/chat files, backend route/schema/config/service/agent files, and the existing architecture/readme documentation used only for contradiction checks. No requested online source file was unavailable. The `.env`, cloud credentials, and live cloud resources were intentionally not inspected; those are environment/deployment values, not source files needed to establish the call graph.
