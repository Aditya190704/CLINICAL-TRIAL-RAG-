
"""Evidence-grounded chat for selected clinical trials.

Responsibilities:
- Retrieve evidence only from the trials selected by the user.
- Rank trial passages against the user's question.
- Generate an answer grounded in retrieved evidence.
- Return structured citation metadata for clickable frontend links.
- Fall back to local processed chunks when BigQuery returns no matching rows.

This module does not make the final clinical eligibility decision.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from google.cloud import bigquery
from google import genai

from app.config import settings
from app.services.embeddings import embed
from app.services.trial_store import chunks, trials

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 4000
MAX_TRIAL_IDS = 10
MAX_EVIDENCE_PER_TRIAL = 4
MAX_TOTAL_EVIDENCE = 12
MAX_EVIDENCE_CHARS = 3000
MAX_ANSWER_CHARS = 12000

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "how", "i", "in", "into", "is", "it", "its", "may", "might",
    "of", "on", "or", "our", "should", "that", "the", "their", "them",
    "there", "these", "they", "this", "those", "to", "was", "we", "were",
    "what", "when", "which", "who", "why", "will", "with", "would",
    "you", "your",
}


def _normalize_trial_ids(trial_ids: list[str]) -> list[str]:
    """Validate and normalize ClinicalTrials.gov identifiers."""
    if not trial_ids:
        raise ValueError("Select at least one clinical trial.")

    if len(trial_ids) > MAX_TRIAL_IDS:
        raise ValueError(f"Select no more than {MAX_TRIAL_IDS} trials at a time.")

    normalized: list[str] = []
    for trial_id in trial_ids:
        value = str(trial_id).strip().upper()

        if not re.fullmatch(r"NCT\d{8}", value):
            raise ValueError(f"Invalid clinical trial identifier: {value}")

        if value not in normalized:
            normalized.append(value)

    return normalized


def _validate_question(question: str) -> str:
    question = (question or "").strip()

    if not question:
        raise ValueError("Enter a question.")

    if len(question) > MAX_QUESTION_LENGTH:
        raise ValueError(
            f"Question must be no longer than {MAX_QUESTION_LENGTH} characters."
        )

    return question


def _trial_lookup() -> dict[str, dict[str, Any]]:
    """Build an NCT ID lookup without logging patient information."""
    result: dict[str, dict[str, Any]] = {}

    for trial in trials() or []:
        if not isinstance(trial, dict):
            continue

        nct_id = str(trial.get("nct_id", "")).strip().upper()
        if nct_id:
            result[nct_id] = trial

    return result


def _get_trial_title(nct_id: str, trial_lookup: dict[str, dict[str, Any]]) -> str:
    trial = trial_lookup.get(nct_id, {})
    return str(
        trial.get("brief_title")
        or trial.get("title")
        or trial.get("official_title")
        or nct_id
    )


def _get_trial_url(nct_id: str) -> str:
    """Generate a canonical ClinicalTrials.gov study URL."""
    return f"https://clinicaltrials.gov/study/{nct_id}"


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
        if len(token) > 1 and token not in _STOP_WORDS
    ]


def _lexical_score(question: str, text: str) -> float:
    """Small local-store fallback score; not a clinical eligibility score."""
    question_tokens = Counter(_tokenize(question))
    passage_tokens = Counter(_tokenize(text))

    if not question_tokens or not passage_tokens:
        return 0.0

    overlap = sum(
        min(count, passage_tokens.get(token, 0))
        for token, count in question_tokens.items()
    )

    # Normalize the overlap so long passages do not automatically win.
    denominator = math.sqrt(
        sum(question_tokens.values()) * sum(passage_tokens.values())
    )
    return overlap / denominator if denominator else 0.0


def _cosine_similarity(query_vector: list[float], document_vector: Any) -> float:
    """Compute cosine similarity for a query and a stored embedding."""
    if not isinstance(document_vector, (list, tuple)):
        return 0.0

    try:
        document = [float(value) for value in document_vector]
        query = [float(value) for value in query_vector]
    except (TypeError, ValueError):
        return 0.0

    if not query or len(query) != len(document):
        return 0.0

    if not all(math.isfinite(value) for value in query + document):
        return 0.0

    dot_product = sum(a * b for a, b in zip(query, document))
    query_norm = math.sqrt(sum(value * value for value in query))
    document_norm = math.sqrt(sum(value * value for value in document))

    if query_norm == 0 or document_norm == 0:
        return 0.0

    return dot_product / (query_norm * document_norm)


def _bigquery_table() -> str:
    project = settings.gcp_project
    dataset = settings.bigquery_dataset
    table = settings.bigquery_chunks_table

    if not project or not dataset or not table:
        raise RuntimeError(
            "BigQuery configuration is incomplete. Check GCP_PROJECT, "
            "BIGQUERY_DATASET, and BIGQUERY_CHUNKS_TABLE."
        )

    # These values come from application configuration, not user input.
    return f"`{project}.{dataset}.{table}`"


def _retrieve_bigquery_evidence(
    question: str,
    selected_trial_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch chunks belonging to the selected trials and rank them by similarity.

    Unlike a global VECTOR_SEARCH followed by a trial-ID filter, this query
    restricts rows to the selected NCT IDs before ranking the results.
    """
    query_vectors = embed([question], task_type="RETRIEVAL_QUERY")

    if not query_vectors or not query_vectors[0]:
        raise RuntimeError("The embedding service returned an empty query vector.")

    query_vector = [float(value) for value in query_vectors[0]]
    table = _bigquery_table()

    sql = f"""
        SELECT
            CAST(chunk_id AS STRING) AS chunk_id,
            UPPER(CAST(nct_id AS STRING)) AS nct_id,
            CAST(chunk_text AS STRING) AS chunk_text,
            CAST(chunk_type AS STRING) AS chunk_type,
            CAST(metadata_json AS STRING) AS metadata_json,
            embedding
        FROM {table}
        WHERE UPPER(CAST(nct_id AS STRING)) IN UNNEST(@trial_ids)
    """

    client = bigquery.Client(
        project=settings.gcp_project,
        location=settings.bq_location,
    )

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter(
                    "trial_ids",
                    "STRING",
                    selected_trial_ids,
                )
            ]
        )

        rows = client.query(sql, job_config=job_config).result()
        ranked: list[dict[str, Any]] = []

        for row in rows:
            nct_id = str(row.get("nct_id") or "").upper()
            text = str(row.get("chunk_text") or "").strip()

            # Defend against unexpected or malformed rows.
            if nct_id not in selected_trial_ids or not text:
                continue

            score = _cosine_similarity(query_vector, row.get("embedding"))

            ranked.append(
                {
                    "chunk_id": str(row.get("chunk_id") or ""),
                    "nct_id": nct_id,
                    "section": str(row.get("chunk_type") or "Trial information"),
                    "text": text,
                    "score": score,
                    "metadata_json": row.get("metadata_json"),
                    "url": _get_trial_url(nct_id),
                }
            )

        return _select_evidence(ranked, selected_trial_ids)

    finally:
        client.close()


def _normalize_local_chunk(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Convert supported local chunk formats to one internal representation."""
    nct_id = str(chunk.get("nct_id") or "").strip().upper()

    text = str(
        chunk.get("chunk_text")
        or chunk.get("text")
        or chunk.get("content")
        or ""
    ).strip()

    if not re.fullmatch(r"NCT\d{8}", nct_id) or not text:
        return None

    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "nct_id": nct_id,
        "section": str(
            chunk.get("chunk_type")
            or chunk.get("section")
            or "Trial information"
        ),
        "text": text,
        "metadata_json": chunk.get("metadata_json"),
        "url": _get_trial_url(nct_id),
    }


def _retrieve_local_evidence(
    question: str,
    selected_trial_ids: list[str],
) -> list[dict[str, Any]]:
    """Fallback for local processed chunks when BigQuery has no matching rows."""
    selected = set(selected_trial_ids)
    ranked: list[dict[str, Any]] = []

    for chunk in chunks() or []:
        if not isinstance(chunk, dict):
            continue

        item = _normalize_local_chunk(chunk)
        if not item or item["nct_id"] not in selected:
            continue

        item["score"] = _lexical_score(question, item["text"])
        ranked.append(item)

    return _select_evidence(ranked, selected_trial_ids)


def _select_evidence(
    ranked: list[dict[str, Any]],
    selected_trial_ids: list[str],
) -> list[dict[str, Any]]:
    """Select the highest-ranked evidence while retaining trial coverage."""
    ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)

    per_trial_count: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in ranked:
        nct_id = item["nct_id"]
        text = item["text"]
        dedupe_key = (nct_id, re.sub(r"\s+", " ", text).strip().lower())

        if dedupe_key in seen:
            continue

        if per_trial_count[nct_id] >= MAX_EVIDENCE_PER_TRIAL:
            continue

        seen.add(dedupe_key)
        selected.append(item)
        per_trial_count[nct_id] += 1

        if len(selected) >= MAX_TOTAL_EVIDENCE:
            break

    # Keep the selected-trial list available for downstream logic. Trials
    # with no retrieved passages are not given fabricated evidence.
    return selected


def retrieve_for_chat(
    question: str,
    trial_ids: list[str],
    top_k_per_trial: int = MAX_EVIDENCE_PER_TRIAL,
) -> list[dict[str, Any]]:
    """Retrieve ranked evidence for the user's selected trials.

    The optional top_k_per_trial argument is retained for compatibility with
    callers using the previous interface.
    """
    question = _validate_question(question)
    selected_trial_ids = _normalize_trial_ids(trial_ids)

    try:
        evidence = _retrieve_bigquery_evidence(question, selected_trial_ids)
        if evidence:
            return evidence

        logger.info(
            "No matching BigQuery chunks for selected trials; trying local chunks."
        )
    except Exception as exc:
        # Do not log the question, patient case, or retrieved medical text.
        logger.warning(
            "BigQuery chat retrieval failed (%s); trying local processed chunks.",
            type(exc).__name__,
        )

    local_evidence = _retrieve_local_evidence(question, selected_trial_ids)

    if not local_evidence:
        logger.info("No evidence found for the selected trials.")

    return local_evidence


def build_evidence_from_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize retrieved passages into the evidence format used by the LLM."""
    result: list[dict[str, Any]] = []

    for candidate in candidates:
        nct_id = str(candidate.get("nct_id") or "").upper()
        text = str(candidate.get("text") or "").strip()

        if not re.fullmatch(r"NCT\d{8}", nct_id) or not text:
            continue

        result.append(
            {
                "nct_id": nct_id,
                "section": str(candidate.get("section") or "Trial information"),
                "text": text[:MAX_EVIDENCE_CHARS],
                "url": _get_trial_url(nct_id),
                "score": candidate.get("score", 0.0),
            }
        )

    return result


def _format_evidence(evidence: list[dict[str, Any]]) -> str:
    blocks: list[str] = []

    for index, item in enumerate(evidence, start=1):
        blocks.append(
            f"[Evidence {index}]\n"
            f"Trial ID: {item['nct_id']}\n"
            f"Section: {item['section']}\n"
            f"Source URL: {item['url']}\n"
            f"Trial text:\n{item['text'][:MAX_EVIDENCE_CHARS]}"
        )

    return "\n\n".join(blocks)


def answer_question(question: str, evidence: list[dict[str, Any]]) -> str:
    """Generate an evidence-grounded answer with Gemini."""
    if not evidence:
        return (
            "I couldn't retrieve supporting text from the selected trials for "
            "this question. Try rephrasing it or selecting a trial with relevant "
            "information. I won't infer an answer without trial evidence."
        )

    evidence_text = _format_evidence(evidence)

    prompt = f"""
You are a clinical-trial information assistant.

Answer the user's question using ONLY the trial evidence supplied below.

Rules:
1. Do not invent eligibility criteria, study results, trial status, or facts.
2. Clearly distinguish what the source explicitly states from what it does not state.
3. If the evidence is insufficient, say so directly.
4. If evidence from different trials differs, explain the difference and name
   the relevant NCT identifier.
5. For eligibility questions, distinguish inclusion criteria, exclusion
   criteria, missing information, and confirmed evidence. Do not declare a
   patient eligible from partial evidence.
6. Do not treat retrieval relevance as proof of eligibility or treatment benefit.
7. Do not provide a treatment recommendation or replace clinician review.
8. Refer to evidence by its [Evidence N] label when useful. Citation links will
   be attached separately by the application.
9. Never claim that a fact is present in the trial text unless it appears in
   the supplied evidence.

USER QUESTION:
{question}

RETRIEVED TRIAL EVIDENCE:
{evidence_text}

Write a clear, direct answer. Include a short "What the evidence supports"
section and, where relevant, a "What remains unknown" section.
""".strip()

    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )

        answer = (getattr(response, "text", None) or "").strip()
        if not answer:
            raise RuntimeError("Gemini returned an empty answer.")

        return answer[:MAX_ANSWER_CHARS]

    finally:
        client.close()


def chat_answer(
    question: str,
    trial_ids: list[str],
    patient_case: str | None = None,
) -> dict[str, Any]:
    """Answer a question about selected trials and return citation metadata."""
    question = _validate_question(question)
    selected_trial_ids = _normalize_trial_ids(trial_ids)

    evidence = retrieve_for_chat(question, selected_trial_ids)
    evidence = build_evidence_from_candidates(evidence)

    if not evidence:
        return {
            "answer": (
                "I couldn't find usable evidence in the selected trials for this "
                "question. Please try another question or verify that the selected "
                "trials have been indexed."
            ),
            "citations": [],
            "missing_info": (
                "No relevant trial passages were retrieved for the selected trials."
            ),
        }

    # Patient context is optional. It is included only to help interpret the
    # user's question, not as a source of trial facts.
    contextual_question = question
    if patient_case and patient_case.strip():
        safe_case = patient_case.strip()[:8000]
        contextual_question = (
            f"Patient context supplied by the user (not trial evidence):\n"
            f"{safe_case}\n\n"
            f"User question:\n{question}"
        )

    answer = answer_question(contextual_question, evidence)
    trial_lookup = _trial_lookup()

    citations: list[dict[str, Any]] = []
    seen_citations: set[tuple[str, str, str]] = set()

    for item in evidence:
        nct_id = item["nct_id"]
        section = item["section"]
        excerpt = item["text"][:300].strip()

        citation_key = (nct_id, section, excerpt)
        if citation_key in seen_citations:
            continue

        seen_citations.add(citation_key)
        citations.append(
            {
                "nct_id": nct_id,
                "trial_title": _get_trial_title(nct_id, trial_lookup),
                "section": section,
                "excerpt": excerpt,
                "url": _get_trial_url(nct_id),
            }
        )

    return {
        "answer": answer,
        "citations": citations,
        "missing_info": None,
    }
