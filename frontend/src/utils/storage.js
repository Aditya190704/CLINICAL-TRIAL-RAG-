/**
 * Clear keys written by the retired browser-only session implementation.
 * Patient cases and matching sessions now come from the authenticated API.
 */
export function clearAllStorage() {
  try {
    window.sessionStorage.removeItem("clinical_trial_rag_sessions_v2");
    window.sessionStorage.removeItem("clinical_trial_rag_active_id_v2");
  } catch (error) {
    // Storage can be unavailable in restricted browser contexts.
    console.warn("Failed to clear legacy session storage:", error);
  }
}
