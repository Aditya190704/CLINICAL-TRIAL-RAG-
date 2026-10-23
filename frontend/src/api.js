/**
 * API service for communicating with the FastAPI backend.
 */

const API_BASE = "";

/**
 * @typedef {Object} MatchResponse
 * @property {Object} patient_profile
 * @property {Array<Object>} matches
 * @property {string} disclaimer
 * @property {number} latency_seconds
 * @property {string|null} [emergency_notice] Present when urgent screening stops matching.
 * @property {string[]} [missing_key_facts] Plain-language facts absent from the validated profile.
 * @property {string[]} [conflicting_facts] Conflicts detected in supported case text.
 * @property {Array<{nct_id: string, title: string, reason: string}>} [ruled_out_trials]
 * @property {string|null} [result_message] Search-specific empty-state explanation.
 */

/**
 * @typedef {Object} ChatResponse
 * @property {string} answer
 * @property {Array<Object>} citations
 * @property {string|null} missing_info
 * @property {string|null} session_id Client-provided identifier; not server-side memory.
 */

async function request(endpoint, options = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
  } catch (error) {
    throw new Error(
      "Cannot connect to the backend server. Please verify that FastAPI is running on http://localhost:8000."
    );
  }

  const raw = await response.text();
  let data;

  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error(
      `The server returned an invalid response: ${raw.slice(0, 200)}`
    );
  }

  if (!response.ok) {
    const detail = data?.detail || data?.message || raw;
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail)
    );
  }

  return data;
}

/**
 * Match a de-identified patient case against clinical trials.
 * @param {string} patientCase
 * @returns {Promise<MatchResponse>}
 */
export async function matchPatient(patientCase) {
  if (!patientCase || !patientCase.trim()) {
    throw new Error("Please enter a patient case before matching trials.");
  }

  return request("/api/match", {
    method: "POST",
    body: JSON.stringify({
      patient_case: patientCase.trim(),
    }),
  });
}

/**
 * Ask a follow-up question grounded strictly in the retrieved trials.
 * @param {Object} params
 * @param {string} params.question
 * @param {Array<string>} params.trialIds
 * @param {string} [params.patientCase]
 * @param {string} [params.sessionId]
 * @returns {Promise<ChatResponse>}
 */
export async function askTrialQuestion({
  question,
  trialIds,
  patientCase = null,
  sessionId = null,
}) {
  if (!question || !question.trim()) {
    throw new Error("Please enter a question.");
  }

  if (!Array.isArray(trialIds) || trialIds.length === 0) {
    throw new Error("At least one trial ID is required for Q&A.");
  }

  return request("/api/trials/chat", {
    method: "POST",
    body: JSON.stringify({
      question: question.trim(),
      trial_ids: trialIds,
      patient_case: patientCase ? patientCase.trim() : null,
      session_id: sessionId || null,
    }),
  });
}

/**
 * Check backend health & trial indexing status.
 * @returns {Promise<{status: string, trials_indexed?: number}>}
 */
export async function checkHealth() {
  try {
    return await request("/api/health", { method: "GET" });
  } catch {
    return { status: "offline", trials_indexed: 0 };
  }
}

export default {
  matchPatient,
  askTrialQuestion,
  checkHealth,
};
