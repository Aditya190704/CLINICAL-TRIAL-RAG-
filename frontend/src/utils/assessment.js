/** Count criterion outcomes for one trial assessment. */
export function countCriteria(criteria = []) {
  return criteria.reduce((counts, item) => {
    if (item.impact === "SUPPORTS") counts.met += 1;
    else if (item.impact === "BLOCKS") counts.blocking += 1;
    else counts.unknown += 1;
    return counts;
  }, { met: 0, blocking: 0, unknown: 0 });
}

/** Use the saved assessment first, with a cautious fallback when it is absent. */
export function getAssessmentSummary(match, counts) {
  if (match?.summary) return match.summary;
  if (counts.blocking) {
    return "One or more assessed criteria may conflict with this patient case. Review the evidence and confirm against the official trial record.";
  }
  return "The available criteria do not establish eligibility. Some information may be missing or unassessed; a qualified clinical team must review the official criteria.";
}
