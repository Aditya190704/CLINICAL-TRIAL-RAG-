/**
 * Safe versioned sessionStorage helpers for session persistence.
 * Note: sessionStorage is tab-scoped by design in browsers.
 */

const SESSIONS_STORAGE_KEY = "clinical_trial_rag_sessions_v2";
const ACTIVE_SESSION_KEY = "clinical_trial_rag_active_id_v2";

/**
 * Safely load all sessions from sessionStorage.
 * @returns {Array<Object>} List of saved session objects.
 */
export function loadSessionsFromStorage() {
  try {
    const raw = window.sessionStorage.getItem(SESSIONS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter(
        (s) => s && typeof s === "object" && typeof s.id === "string"
      );
    }
    return [];
  } catch (error) {
    console.warn("Failed to load sessions from sessionStorage:", error);
    return [];
  }
}

/**
 * Safely save all sessions to sessionStorage.
 * @param {Array<Object>} sessions
 */
export function saveSessionsToStorage(sessions) {
  try {
    if (!Array.isArray(sessions)) return;
    window.sessionStorage.setItem(
      SESSIONS_STORAGE_KEY,
      JSON.stringify(sessions)
    );
  } catch (error) {
    console.warn("Failed to save sessions to sessionStorage (quota?):", error);
  }
}

/**
 * Safely load active session ID from sessionStorage.
 * @returns {string|null}
 */
export function loadActiveSessionId() {
  try {
    return window.sessionStorage.getItem(ACTIVE_SESSION_KEY) || null;
  } catch (error) {
    console.warn("Failed to load active session ID from sessionStorage:", error);
    return null;
  }
}

/**
 * Safely save active session ID to sessionStorage.
 * @param {string|null} id
 */
export function saveActiveSessionId(id) {
  try {
    if (id) {
      window.sessionStorage.setItem(ACTIVE_SESSION_KEY, String(id));
    } else {
      window.sessionStorage.removeItem(ACTIVE_SESSION_KEY);
    }
  } catch (error) {
    console.warn("Failed to save active session ID:", error);
  }
}

/**
 * Clear all session storage keys used by this application.
 */
export function clearAllStorage() {
  try {
    window.sessionStorage.removeItem(SESSIONS_STORAGE_KEY);
    window.sessionStorage.removeItem(ACTIVE_SESSION_KEY);
  } catch (error) {
    console.warn("Failed to clear sessionStorage:", error);
  }
}

