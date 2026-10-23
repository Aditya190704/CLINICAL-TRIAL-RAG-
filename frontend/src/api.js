/**
 * API service for communicating with the FastAPI backend.
 */

import { auth } from "./firebase";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

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
        ...(auth?.currentUser
          ? { Authorization: `Bearer ${await auth.currentUser.getIdToken()}` }
          : {}),
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
export async function matchPatient(patientCase, sessionId) {
  if (!patientCase || !patientCase.trim()) {
    throw new Error("Please enter a patient case before matching trials.");
  }

  return request("/api/match", {
    method: "POST",
    body: JSON.stringify({
      patient_case: patientCase.trim(),
      session_id: sessionId || null,
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
  messageId = null,
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
      session_id: sessionId || null,
      message_id: messageId || null,
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

export async function initializeProfile(displayName) {
  return request("/api/auth/profile", {
    method: "POST",
    body: JSON.stringify({ display_name: displayName }),
  });
}

export async function listSessions() {
  return request("/api/sessions", { method: "GET" });
}

export async function createSession(title = "New Patient Session") {
  return request("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function getSession(sessionId) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "GET" });
}

export async function renameRemoteSession(sessionId, title) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function deleteRemoteSession(sessionId) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}

export async function clearRemoteSessions() {
  return request("/api/sessions", { method: "DELETE" });
}

export async function clearRemoteChat(sessionId) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, { method: "DELETE" });
}

export async function clearRemoteResult(sessionId) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}/result`, { method: "DELETE" });
}

export default {
  matchPatient,
  askTrialQuestion,
  checkHealth,
  initializeProfile,
  listSessions,
  createSession,
  getSession,
  renameRemoteSession,
  deleteRemoteSession,
  clearRemoteSessions,
  clearRemoteChat,
  clearRemoteResult,
};
