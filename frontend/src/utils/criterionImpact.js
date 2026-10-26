export function criterionImpactLabel(impact, criterionType) {
  const normalizedImpact = String(impact || "UNKNOWN").toUpperCase();
  const normalizedType = String(criterionType || "").toUpperCase();

  if (normalizedImpact === "UNKNOWN") return "Could not assess";
  if (!["SUPPORTS", "BLOCKS"].includes(normalizedImpact)) return "Could not assess";
  if (normalizedType === "INCLUSION") {
    return normalizedImpact === "SUPPORTS" ? "Met" : "Not met";
  }
  if (normalizedType === "EXCLUSION") {
    return normalizedImpact === "BLOCKS" ? "Met" : "Not met";
  }
  return normalizedImpact === "SUPPORTS" ? "Supports trial" : "Potential blocker";
}
