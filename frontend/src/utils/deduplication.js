/**
 * Deduplication utilities to prevent repetitive or duplicated content in outputs.
 */

/**
 * Deduplicate a list of criteria results.
 * Compares normalized criterion_quote + impact + patient_evidence.
 * @param {Array<Object>} criteria
 * @returns {Array<Object>}
 */
export function deduplicateCriteria(criteria) {
  if (!Array.isArray(criteria)) return [];

  const seen = new Set();
  const result = [];

  for (const item of criteria) {
    if (!item || typeof item !== "object") continue;

    const quote = (item.criterion_quote || item.criterion || item.text || "")
      .trim()
      .toLowerCase();
    const impact = (item.impact || "").trim().toUpperCase();
    const evidence = (item.patient_evidence || item.patient_evidence_quote || "")
      .trim()
      .toLowerCase();

    // Unique fingerprint for this criterion
    const key = `${impact}:::${quote}:::${evidence}`;

    if (!quote && !evidence) continue;
    if (seen.has(key)) continue;

    seen.add(key);
    result.push(item);
  }

  return result;
}

/**
 * Deduplicate a list of retrieved passages.
 * Compares chunk_type + normalized text.
 * @param {Array<Object>} passages
 * @returns {Array<Object>}
 */
export function deduplicatePassages(passages) {
  if (!Array.isArray(passages)) return [];

  const seen = new Set();
  const result = [];

  for (const p of passages) {
    if (!p || typeof p !== "object") continue;

    const type = (p.chunk_type || "passage").trim().toLowerCase();
    const text = (p.text || "").trim();

    if (!text) continue;

    // Normalize whitespace for comparison
    const normText = text.toLowerCase().replace(/\s+/g, " ").slice(0, 200);
    const key = `${type}:::${normText}`;

    if (seen.has(key)) continue;

    seen.add(key);
    result.push(p);
  }

  return result;
}

/**
 * Deduplicate chat citations by NCT ID and section.
 * @param {Array<Object>} citations
 * @returns {Array<Object>}
 */
export function deduplicateCitations(citations) {
  if (!Array.isArray(citations)) return [];

  const seen = new Set();
  const result = [];

  for (const c of citations) {
    if (!c || typeof c !== "object") continue;
    const nctId = (c.nct_id || "").trim().toUpperCase();
    const section = (c.section || "").trim().toLowerCase();
    const key = `${nctId}:::${section}`;

    if (!nctId) continue;
    if (seen.has(key)) continue;

    seen.add(key);
    result.push(c);
  }

  return result;
}

