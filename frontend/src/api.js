/**
 * API service for communicating with the FastAPI backend.
 */

const API_BASE = "";

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
 * @returns {Promise<Object>} MatchResponse
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
 * @returns {Promise<Object>} ChatResponse
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
