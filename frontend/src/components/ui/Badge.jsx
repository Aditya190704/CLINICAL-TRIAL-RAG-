import React from "react";
import { criterionImpactLabel } from "../../utils/criterionImpact";

const VERDICTS = {
  ELIGIBLE: { label: "Requires clinical review", icon: "!", variant: "warning" },
  POSSIBLY_ELIGIBLE: { label: "Possibly eligible", icon: "!", variant: "warning" },
  COULD_NOT_ASSESS: { label: "Could not assess", icon: "?", variant: "neutral" },
  EXCLUDED: { label: "Excluded", icon: "×", variant: "danger" },
};

const IMPACTS = {
  SUPPORTS: { label: "Supports trial", icon: "✓", variant: "success" },
  BLOCKS: { label: "Potential blocker", icon: "×", variant: "danger" },
  UNKNOWN: { label: "Could not assess", icon: "?", variant: "neutral" },
};

/** Small accessible status label for trial verdicts and criterion outcomes. */
export default function Badge({
  children,
  verdict,
  impact,
  criterionType,
  variant = "default",
  size = "md",
  className = "",
  icon,
  title,
}) {
  const configuration = verdict
    ? VERDICTS[String(verdict).toUpperCase()] || { label: String(verdict), icon: "•", variant: "neutral" }
    : impact ? {
      ...(IMPACTS[String(impact).toUpperCase()] || { label: String(impact), icon: "•", variant: "neutral" }),
      label: criterionImpactLabel(impact, criterionType),
    } : null;

  if (!configuration) {
    return <span title={title} className={`badge badge-${variant} badge-${size} ${className}`}>
      {icon && <span className="badge-icon" aria-hidden="true">{icon}</span>}
      <span>{children}</span>
    </span>;
  }

  return (
    <span title={title || configuration.label} className={`badge badge-${configuration.variant} badge-${size} ${className}`}>
      <span className="badge-icon" aria-hidden="true">{icon || configuration.icon}</span>
      <span>{children || configuration.label}</span>
    </span>
  );
}
