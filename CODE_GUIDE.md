# Code Guide

This guide explains where the main parts of the Clinical Trial RAG application live. The code is grouped by responsibility so a change to one feature does not need to be mixed into unrelated files.

## Application flow

1. The React app in `frontend/src/App.jsx` connects the workspace, sign-in state, active search session, and screen-level navigation.
2. Reusable UI pieces live under `frontend/src/components/`. Result cards and assessment details are under `components/results/`; session history is under `components/session/`.
3. `frontend/src/api.js` sends requests to FastAPI. `frontend/src/hooks/useSessionManager.js` loads and updates a user's saved sessions.
4. `backend/app/main.py` creates the FastAPI app, applies request middleware, and exposes API routes.
5. `backend/app/agents/workflow.py` coordinates patient parsing, trial retrieval, evidence review, and response creation.
6. Individual backend services live in `backend/app/services/`. Each service handles one responsibility such as chat evidence, authentication, trial storage, or eligibility assessment.

## Backend modules

| File | Responsibility |
| --- | --- |
| `backend/app/main.py` | API setup, request middleware, health checks, and HTTP routes. |
| `backend/app/schemas.py` | Validated request and response data shapes. |
| `backend/app/config.py` | Environment-based application settings. |
| `backend/app/agents/workflow.py` | Runs the matching steps and combines their results. |
| `backend/app/agents/tasks.py` | Defines focused AI tasks and their instructions. |
| `backend/app/agents/tools.py` | Gives the workflow controlled access to trial retrieval. |
| `backend/app/services/patient_parser.py` | Extracts supported patient facts from the case text. |
| `backend/app/services/retriever.py` | Finds trial records relevant to a patient case. |
| `backend/app/services/eligibility_judge.py` | Checks criterion assessments and produces a cautious verdict. |
| `backend/app/services/chat.py` | Finds trial evidence and prepares cited answers to follow-up questions. |
| `backend/app/services/user_data.py` | Reads and writes user profiles, search sessions, results, and chat history. |
| `backend/app/services/firebase_auth.py` | Verifies Firebase identity tokens for protected requests. |
| `backend/app/services/safety.py` | Applies patient-data and clinical safety checks. |

## Frontend modules

| Folder or file | Responsibility |
| --- | --- |
| `frontend/src/auth/` | Sign-in, account creation, and authenticated user state. |
| `frontend/src/components/layout/` | Shared page shell, header, footer, and welcome content. |
| `frontend/src/components/results/` | Trial results, criterion evidence, passages, and assessment summary. |
| `frontend/src/components/session/` | Session list, selection, rename, and delete controls. |
| `frontend/src/components/chat/` | Trial evidence chat UI. |
| `frontend/src/components/ui/` | Small reusable buttons, badges, dialogs, and loading states. |
| `frontend/src/hooks/` | Reusable stateful behavior such as session management and notifications. |
| `frontend/src/utils/` | Formatting, evidence report, deduplication, and browser storage helpers. |
| `frontend/src/api.js` | Authenticated communication with the backend. |

## Comment style

Comments explain why a decision exists or what a block is responsible for. Names and short expressions should explain ordinary code directly; repeating each line in a comment makes changes harder to maintain. Python functions use docstrings for their purpose, while JSX and JavaScript use short comments around non-obvious behavior or grouped sections.

## Safe change checklist

- Keep API request and response shapes in `schemas.py` and update both sides when a shape changes.
- Keep user-owned Firestore reads and writes scoped by the authenticated UID.
- Keep React view components focused on displaying data; move reusable state behavior into hooks and calculations into utilities.
- Keep trial eligibility language cautious and traceable to the evidence shown to the user.
