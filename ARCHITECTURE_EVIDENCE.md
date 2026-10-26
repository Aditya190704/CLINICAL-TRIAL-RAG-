# Architecture Evidence

This evidence map supports the arrows and claims in [ONLINE_ARCHITECTURE.mmd](./ONLINE_ARCHITECTURE.mmd). Paths are relative to the repository root. Function/class names and endpoint decorators are included so each connection can be checked in the current source. A source relationship not established by the checked-out code is explicitly marked **UNVERIFIED** and is not used as a confirmed diagram edge.

## Frontend and identity

| Diagram component / connection | Source | Implemented behavior and supporting relationship |
|---|---|---|
| React app bootstrapping | `frontend/src/main.jsx` — `createRoot`, `AuthProvider` | Wraps `<App />` in `<AuthProvider>` and mounts it at the `root` element. |
| Firebase browser authentication | `frontend/src/firebase.js` — `firebaseApp`, `auth` | Initializes Firebase from `VITE_FIREBASE_*`; exports Firebase Auth only when all web config fields are present. |
| Sign-in, sign-up, reset | `frontend/src/auth/AuthContext.jsx` — `signIn`, `signUp`, `sendPasswordReset`; `frontend/src/auth/AuthScreen.jsx` — `submit`, `handleForgotPassword` | Uses Firebase email/password methods. Signup updates Firebase display name, refreshes the ID token, and calls `initializeProfile`. |
| Auth state to profile request | `frontend/src/auth/AuthContext.jsx` — `onAuthStateChanged`, `loadProfile` | On an authenticated Firebase user, obtains an ID token and fetches `/api/auth/profile`; stores `{ firebaseUser, profile }` in context. |
| Browser API authorization | `frontend/src/api.js` — `request` | Adds an Authorization bearer header from `auth.currentUser.getIdToken()` for requests while a Firebase user is present. `AuthContext.loadProfile` also sends the token for its direct profile fetch. |
| Profile calls | `frontend/src/api.js` — `initializeProfile`; `backend/app/main.py` — `GET /api/auth/profile`, `POST /api/auth/profile` | Signup posts `display_name`; auth-state loading gets the profile. Backend functions call `user_data.get_or_create_profile` or `initialize_profile`. |
| Profile Firestore access | `backend/app/services/user_data.py` — `get_or_create_profile`, `initialize_profile` | Uses `users/{uid}`; the UID argument originates from the verified backend dependency. Assigns/fixes `clinical_technician` role in returned/stored profile data. |
| API auth dependency | `backend/app/services/auth_dependency.py` — `require_firebase_user` | Requires HTTP Bearer credentials, verifies token in a worker thread, rejects absent/invalid identity, and returns UID/email/display name from verified claims. |
| Firebase Admin / Firestore client | `backend/app/services/firebase_auth.py` — `_firebase_app`, `verify_firebase_id_token`, `firestore_client` | Initializes/reuses Firebase Admin; `verify_firebase_id_token` calls Admin `auth.verify_id_token(..., check_revoked=False)`; Firestore client uses the same Admin app. |

## Session loading and ownership

| Diagram component / connection | Source | Implemented behavior and supporting relationship |
|---|---|---|
| Session API calls | `frontend/src/api.js` — `listSessions`, `createSession`, `getSession`, `renameRemoteSession`, `deleteRemoteSession`, `clearRemoteSessions`, `clearRemoteChat`, `clearRemoteResult` | Maps to `/api/sessions`, `/api/sessions/{id}`, `/api/sessions/{id}/messages`, and `/api/sessions/{id}/result` methods. |
| Initial history and first session | `frontend/src/hooks/useSessionManager.js` — effect in `useSessionManager` | Calls `listSessions`; creates a session if empty; normalizes returned sessions; loads first session detail. |
| Open / create / rename / delete | `frontend/src/hooks/useSessionManager.js` — `switchSession`, `createNewSession`, `renameSession`, `deleteSession`, `clearAllSessions` | Uses API helpers and updates active React session state from API responses. |
| Session routes | `backend/app/main.py` — `get_sessions`, `post_session`, `get_session`, `patch_session`, `delete_session_messages`, `delete_session_result`, `delete_one_session`, `delete_all_sessions` | Authenticated endpoints implement list/create/detail/rename/delete/clear operations; each passes `user["uid"]` to user-data functions. |
| Session-scoped Firestore paths | `backend/app/services/user_data.py` — `_session_ref`, `create_session`, `list_sessions`, `get_session` | Builds `users/{uid}/sessions/{session_id}` refs; creates/list sessions there and loads nested `messages` when loading a session. |
| Ownership failure behavior | `backend/app/main.py` — `get_session`, session mutation routes, `match`, `trial_chat`; `backend/app/services/user_data.py` — `_session_ref`, `get_session` | Retrieval/mutation is scoped beneath the verified UID. Missing or foreign session refs produce `None`/`False`, which routes map to 403. |
| Frontend workspace routing | `frontend/src/App.jsx` — `App`, `ClinicalWorkspace` | Shows `AuthScreen` when unauthenticated; authenticated workspace is keyed by Firebase UID and receives the profile/session state. |

## Matching request, workflow, retrieval, and verification

| Diagram component / connection | Source | Implemented behavior and supporting relationship |
|---|---|---|
| Case submission | `frontend/src/App.jsx` — `handleSubmit`; `frontend/src/api.js` — `matchPatient` | Ensures active session, creates a fresh session when existing results are present, and sends `POST /api/match` with `patient_case` and `session_id`. |
| Match request/response schema | `backend/app/schemas.py` — `MatchRequest`, `MatchResponse`, `TrialMatch`, `PatientProfile`, `CriterionResult` | Defines case bounds, optional session ID and returned profile/matches/disclaimer/latency/safety/criteria/passages/session fields. `relevance_score` is documented as similarity, not eligibility probability. |
| Match route and first persistence | `backend/app/main.py` — `match` (`POST /api/match`) | Validates case before storage; checks/creates session; calls `save_search_query`; awaits pipeline; stores full response through `save_match_result`; adds `session_id` to returned response. Failed started searches call `mark_search_failed`. |
| Direct identifier and length checks | `backend/app/services/pipeline.py` — `_validate_case`, `_contains_possible_direct_identifier`, `validate_case` | Checks 40–8,000 characters and regex patterns for email, US SSN, and phone number. Called by route before durable query storage and again by `run_async`. |
| Urgent screen before model/retrieval | `backend/app/services/pipeline.py` — `run_async`; `backend/app/services/safety.py` — `screen_urgent_case` | Runs after route persistence, returns emergency `MatchResponse` if a configured warning phrase is detected. Only then would non-urgent cases continue to `run_workflow_async`. |
| Urgent warning source | `backend/app/services/safety.py` — `URGENT_SIGN_FILE`, `_config`, `screen_urgent_case` | Reads `backend/app/urgent_signs.json`, applies configured phrases and simple negation handling. The warning file's specific phrase contents are deployment/data configuration, not represented as a diagram node. |
| Workflow timeout and dispatch | `backend/app/agents/workflow.py` — `run_workflow_async`, `_run_steps` | `run_workflow_async` wraps deterministic workflow in `asyncio.wait_for`; `_run_steps` removes recognized instruction-like clauses and sequences extraction, safety/profile checks, retrieval, assessment, ranking, and response construction. |
| ADK task definitions | `backend/app/agents/tasks.py` — `extract_patient`, `propose_refinement`, `assess_trial`, `answer_trial_question` | Each calls `run_structured_agent` with a task-specific instruction, JSON data, and Pydantic output schema. |
| ADK task runtime | `backend/app/agents/adk_runtime.py` — `run_structured_agent` | Creates one request-scoped `InMemorySessionService`, Gemini model, `LlmAgent`, and `Runner`; executes one task, validates structured output, deletes the session and closes clients. No `SequentialAgent`/`ParallelAgent` appears in the inspected online call path. |
| Patient fact validation | `backend/app/services/patient_parser.py` — `_validate_profile`; `backend/app/services/safety.py` — `validate_extracted_profile`, `derive_missing_facts`, `detect_supported_conflicts`, `remove_conflicting_fact_mentions`, `safe_search_query` | Safety validation imports parser validation; removes unsupported facts and builds grounded queries; derives missing fields and handles supported age/stage conflicts. |
| Instruction-like text filter | `backend/app/services/untrusted_text.py` — `contains_instruction_like_text`, `remove_instruction_like_clauses` | Recognizes configured instruction-like patterns and removes matching sentences/lines. Workflow, model task inputs, retrieved trial text, and chat evidence call these helpers. |
| Query construction and bounded wrapper | `backend/app/agents/workflow.py` — `_run_steps`; `backend/app/agents/tools.py` — `ApprovedTrialRetrieval.search` | Builds condition/detail query strings, applies safety checks, and permits no more than two wrapper calls. Search runs `retrieve` in a thread with a timeout. |
| Vertex embeddings | `backend/app/services/embeddings.py` — `embed`, `_embed_batch`; `backend/app/config.py` — `Settings.embedding_model`, `embedding_dim`, `gcp_location` | Creates a Vertex AI Gen AI client and calls `models.embed_content` with `RETRIEVAL_QUERY`, configured model/dimension/project/location. Defaults are `text-embedding-005`, 768, `us-central1`; environment may override. |
| BigQuery matching vector search | `backend/app/services/retriever.py` — `retrieve`, `execute_vector_search`, `build_vector_search_sql`; `backend/app/config.py` — BigQuery settings | Embeds query list, parameterizes each query vector and top-k, runs `VECTOR_SEARCH(TABLE project.dataset.table, 'embedding', ..., distance_type => 'COSINE')`. No Vertex AI Vector Search client is used. |
| RRF and chunk aggregation | `backend/app/services/retriever.py` — `fuse_and_deduplicate` | Groups rows by query ID, computes per-trial RRF and best similarity, retains chunk IDs, and returns sorted `Candidate` objects. |
| Candidate and metadata filtering | `backend/app/agents/workflow.py` — `_trial_index`, `_dedupe_candidates`, `_merge_candidates`; `backend/app/services/trial_store.py` — `trials` | Workflow verifies NCT format and corresponding trial metadata, removes duplicates and instruction-like content, then sorts candidates by best similarity/ID. |
| Conditional refinement | `backend/app/agents/workflow.py` — `_run_steps`, `_refinement_query_is_useful`, `_refinement_query_is_profile_grounded`; `backend/app/agents/tasks.py` — `propose_refinement` | Starts only for empty or weak (<0.35) initial retrieval; overlaps with initial assessment tasks; proposal must be useful and profile-grounded before a single second search. Optional failure keeps initial candidates. |
| Assessment concurrency | `backend/app/agents/workflow.py` — nested `assess_candidate`, `assess_candidates`; `backend/app/config.py` — `adk_concurrency`, `candidates_to_judge` | Creates asyncio tasks and gathers them with a semaphore. Default concurrency is 6; assessment shortlist defaults to 10 and is hard-capped at 20. This is application-level concurrency, not ADK `ParallelAgent`. |
| Criterion quotation/evidence verification | `backend/app/services/eligibility_judge.py` — `verify_judge_output`, `_patient_evidence_verified`, `_metastatic_status_is_explicit`, `_age_check` | Requires criterion quote text to appear (normalized) in eligibility text; unsupported patient evidence is downgraded to `UNKNOWN`; explicit metastatic status is checked for metastatic criteria; deterministic age/sex checks can add structured criteria. |
| Deterministic verdict | `backend/app/services/eligibility_judge.py` — `compute_verdict`; `backend/app/agents/workflow.py` — `_verdict_priority`, `_unresolved_count` | Any blocker produces `EXCLUDED`; no support produces `COULD_NOT_ASSESS`; otherwise `POSSIBLY_ELIGIBLE`. Workflow orders candidates by verdict, unknown count, similarity, and NCT ID, then removes excluded results from returned `matches`. |
| Trial metadata/passages | `backend/app/agents/workflow.py` — `_trial_index`, `_chunk_index`, `_get_passages`, `_build_match`; `backend/app/services/trial_store.py` — `trials`, `chunks` | Reads trial metadata and chunks separately from vector retrieval; maps candidate chunk IDs to evidence passages; builds final match metadata and ClinicalTrials.gov URL. |
| GCS/local trial corpus source | `backend/app/services/trial_store.py` — `_load_json`, `_read_gcs_json`, `_read_local_json`, `trials`, `chunks`; `backend/app/config.py` — `gcs_bucket`, `gcs_prefix`, `processed_dir` | Tries configured GCS objects first and falls back to local processed JSON; data is cached via `lru_cache`. `backend/app/services/gcs_store.py` is not called by the inspected online path. |
| Match result persistence | `backend/app/services/user_data.py` — `save_search_query`, `mark_search_failed`, `save_match_result` | Updates session state and stores the structured response/result summary and matched NCT IDs in Firestore. |
| Match response UI | `frontend/src/App.jsx` — `handleSubmit`; `frontend/src/components/results/ResultsOverview.jsx`, `TrialTabs.jsx`, `TrialDetailView.jsx`, `ClinicalAssessmentPage.jsx`, `CriteriaSection.jsx`, `PassagesSection.jsx`, `PatientProfileCard.jsx` | App places returned JSON in session state; result components render trial cards, similarity, criteria, passages, profile, missing/conflicting facts, and disclaimer. |

## Chat request and response

| Diagram component / connection | Source | Implemented behavior and supporting relationship |
|---|---|---|
| Chat submission | `frontend/src/components/chat/ChatDrawer.jsx` — `handleSend`; `frontend/src/api.js` — `askTrialQuestion` | Creates `messageId`; sends question, trial IDs, session ID, message ID to `/api/trials/chat`; appends returned answer/citations to React history. `patientCase` is an accepted helper argument but is omitted from JSON. |
| Chat request schema | `backend/app/schemas.py` — `ChatRequest`, `ChatResponse`, `Citation` | Validates question and trial ID list; normalizes ID casing; has optional `patient_case`, `session_id`, and `message_id`; response includes answer, citations, missing info, and session ID. |
| Chat endpoint and ownership | `backend/app/main.py` — `trial_chat` (`POST /api/trials/chat`) | Requires Firebase user, requires saved session, checks ownership through UID-scoped lookup, validates requested NCT IDs against `matchedTrialIds`, performs idempotent lookup, calls chat service, persists turn, and returns schema. |
| Chat metadata validation and evidence retrieval | `backend/app/services/chat.py` — `_chat_answer`, `retrieve_for_chat`, `_retrieve_bigquery_evidence`, `_retrieve_local_evidence` | Validates trial IDs against metadata; embeds question; SQL filters BigQuery rows by selected IDs; Python computes cosine; on empty or failed BigQuery retrieval it falls back to local chunk lexical ranking. Evidence is restricted to selected IDs. |
| Chat result bounds | `backend/app/services/chat.py` — `_select_evidence`, `MAX_EVIDENCE_PER_TRIAL`, `MAX_TOTAL_EVIDENCE` | Deduplicates passages and limits to four per trial and twelve total. |
| Chat model response | `backend/app/services/chat.py` — `answer_question`, `_chat_answer`; `backend/app/agents/tasks.py` — `answer_trial_question` | If evidence exists, sends sanitized selected-trial evidence and question to structured ADK task. If none, returns a fixed no-evidence message without model invocation. |
| Chat citation construction | `backend/app/services/chat.py` — `_chat_answer`, `_get_trial_title`, `_get_trial_url` | Builds citations from retrieved evidence and processed trial metadata. This is not a model-generated citation list or independent answer-quote verification step. |
| Firestore chat persistence | `backend/app/main.py` — `trial_chat`; `backend/app/services/user_data.py` — `persist_chat_turn`, `load_chat_turn`, `get_session` | Stores paired user/assistant documents with turn ID, answer, citations, timestamp; loading a session reconstructs turns. |
| Chat response rendering | `frontend/src/components/chat/ChatDrawer.jsx` — `handleSend`, `FormattedMessage` | Displays answer, source IDs, sections, clickable URLs, and optionally clears saved chat through the session API. |

## Diagram edges and unverified relationships

- Solid arrows depict calls/data paths directly supported by the listed source functions.
- Dashed arrows depict code-controlled branches: urgent-screen early return, weak/empty retrieval refinement, optional refinement failure, local chat evidence fallback, and the no-evidence chat response.
- **UNVERIFIED:** actual deployment-specific project IDs, environment overrides, cloud resource existence/contents, BigQuery vector-index configuration, IAM/ADC identity, and live model service settings. They are deliberately not inferred from environment files or credentials.
- **UNVERIFIED:** any UI-to-Firestore browser call, production ingress/load balancer, hosting topology, a separate Vertex AI Vector Search endpoint, ADK `SequentialAgent`/`ParallelAgent`, a server-side chat memory agent, or online GCS persistence. These are not shown as confirmed diagram edges because the inspected online code does not implement them.

## Exact source inventory inspected

### Frontend

- `frontend/src/main.jsx`
- `frontend/src/App.jsx`
- `frontend/src/api.js`
- `frontend/src/firebase.js`
- `frontend/src/auth/AuthContext.jsx`
- `frontend/src/auth/AuthScreen.jsx`
- `frontend/src/hooks/useSessionManager.js`
- `frontend/src/components/chat/ChatDrawer.jsx`
- `frontend/src/components/results/ClinicalAssessmentPage.jsx`
- `frontend/src/components/results/CriteriaSection.jsx`
- `frontend/src/components/results/PassagesSection.jsx`
- `frontend/src/components/results/PatientProfileCard.jsx`
- `frontend/src/components/results/ResultsOverview.jsx`
- `frontend/src/components/results/TrialDetailView.jsx`
- `frontend/src/components/results/TrialTabs.jsx`

### Backend

- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/app/config.py`
- `backend/app/safe_logging.py`
- `backend/app/services/auth_dependency.py`
- `backend/app/services/firebase_auth.py`
- `backend/app/services/user_data.py`
- `backend/app/services/pipeline.py`
- `backend/app/agents/workflow.py`
- `backend/app/agents/tasks.py`
- `backend/app/agents/adk_runtime.py`
- `backend/app/agents/tools.py`
- `backend/app/services/patient_parser.py`
- `backend/app/services/retriever.py`
- `backend/app/services/embeddings.py`
- `backend/app/services/eligibility_judge.py`
- `backend/app/services/trial_store.py`
- `backend/app/services/chat.py`
- `backend/app/services/gcs_store.py`
- `backend/app/services/safety.py`
- `backend/app/services/untrusted_text.py`
- `backend/app/urgent_signs.json` (referenced by `safety.py`; phrase contents not reproduced)
- `backend/tests/test_workflow.py` (workflow behavior/test setup only)

### Documentation compared only for contradiction checks

- `ARCHITECTURE.md`
- `README.md`

No requested online source file was unavailable. `.env` files, credentials, and live cloud resources were not inspected to avoid exposing secrets and because source alone cannot establish deployed runtime values.
