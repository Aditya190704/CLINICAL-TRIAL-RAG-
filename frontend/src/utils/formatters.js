/**
 * Formatters for clinical data, dates, scores, and text truncation.
 */

/**
 * Format a timestamp into a human-friendly relative or calendar string.
 * @param {number|string|Date} timestamp
 * @returns {string} e.g. "Just now", "5m ago", "Today at 2:30 PM", or "Oct 21, 2026"
 */
export function formatRelativeTime(timestamp) {
  if (!timestamp) return "Recently";
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return "Recently";

  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 30) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay === 1) return "Yesterday";
  if (diffDay < 7) return `${diffDay}d ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  });
}

/**
 * Format exact date and time.
 * @param {number|string|Date} timestamp
 * @returns {string}
 */
export function formatFullDateTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return "";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Format relevance similarity score to percentage.
 * @param {number|string} score
 * @returns {string} e.g. "92%"
 */
export function formatScore(score) {
  if (score === undefined || score === null || score === "") return "0%";
  const num = Number(score);
  if (isNaN(num)) return "0%";
  const clamped = Math.max(0, Math.min(1, num <= 1 ? num : num / 100));
  return `${Math.round(clamped * 100)}%`;
}

/**
 * Safely truncate a string with ellipsis.
 * @param {string} text
 * @param {number} maxLen
 * @returns {string}
 */
export function truncate(text, maxLen = 80) {
  if (!text || typeof text !== "string") return "";
  const clean = text.trim();
  if (clean.length <= maxLen) return clean;
  return clean.slice(0, maxLen).trim() + "…";
}

/**
 * Generate a smart session title based on the patient case text.
 * E.g. extracts age, diagnosis, or disease stage, or falls back to short summary.
 * @param {string} patientCase
 * @param {Object} [profile]
 * @returns {string}
 */
export function generateSessionTitle(patientCase, profile) {
  if (!patientCase || !patientCase.trim()) return "New Patient Session";

  const explicitAges = [...patientCase.matchAll(/\b(\d{1,3})(?:\s*years?\s*old|-year-old|\s*yo)\b/gi)];
  const caseAge = explicitAges.length === 1 ? Number(explicitAges[0][1]) : null;

  // If we have an extracted profile, build an informative clinical title
  if (profile) {
    const parts = [];
    if (caseAge != null) parts.push(`${caseAge}yo`);
    else if (profile.age_years != null && explicitAges.length === 0) {
      parts.push(`${Math.round(profile.age_years)}yo`);
    }
    if (profile.sex && profile.sex !== "UNKNOWN") {
      parts.push(profile.sex === "FEMALE" ? "Female" : "Male");
    }
    if (profile.primary_conditions && profile.primary_conditions.length > 0) {
      parts.push(profile.primary_conditions[0]);
    }
    if (parts.length >= 2) {
      return parts.join(" • ");
    }
  }

  // Fallback heuristic extraction from text
  const clean = patientCase.trim().replace(/\s+/g, " ");

  // Check for common age/gender patterns, e.g. "62-year-old woman with newly diagnosed stage IIIB..."
  const match = clean.match(
    /^(\d{1,3}[-\s]?year[-\s]?old\s+(?:woman|man|female|male|patient))/i
  );
  if (match) {
    const remainder = clean.slice(match[0].length).replace(/^[,.\s]+(?:with|diagnosed with|having)?\s*/i, "");
    const condition = remainder.split(/[,.]/)[0].trim();
    if (condition && condition.length < 40) {
      return `${match[1]} • ${condition}`;
    }
    return match[1];
  }

  // Otherwise, take first sentence or 45 chars
  const firstSentence = clean.split(/[.?!]/)[0].trim();
  if (firstSentence.length > 0 && firstSentence.length <= 50) {
    return firstSentence;
  }
  return truncate(clean, 42);
}

