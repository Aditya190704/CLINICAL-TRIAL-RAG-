import React from "react";

const VERDICT_CONFIG = {
  ELIGIBLE: {
    label: "Likely eligible",
    icon: "✓",
    variant: "success",
  },
  POSSIBLY_ELIGIBLE: {
    label: "Possibly eligible",
    icon: "!",
    variant: "warning",
  },
  COULD_NOT_ASSESS: {
    label: "Could not assess",
    icon: "?",
    variant: "neutral",
  },
  EXCLUDED: {
    label: "Excluded",
    icon: "✕",
    variant: "danger",
  },
};

const IMPACT_CONFIG = {
  SUPPORTS: {
    label: "Met",
    icon: "✓",
    variant: "success",
  },
  BLOCKS: {
    label: "Blocks",
    icon: "✕",
    variant: "danger",
  },
  UNKNOWN: {
    label: "Could not assess",
    icon: "?",
    variant: "neutral",
  },
};

/**
 * Reusable Badge component for verdicts, impacts, statuses, and chips.
 */
export default function Badge({
  children,
  verdict,
  impact,
  variant = "default",
  size = "md",
  className = "",
  icon = null,
  title,
}) {
  if (verdict) {
    const key = String(verdict).toUpperCase();
    const cfg = VERDICT_CONFIG[key] || {
      label: verdict,
      icon: "•",
      variant: "neutral",
    };
    return (
      <span
        title={title || cfg.label}
        className={`badge badge-${cfg.variant} badge-${size} ${className}`}
      >
        <span className="badge-icon">{icon || cfg.icon}</span>
        <span>{children || cfg.label}</span>
      </span>
    );
  }

  if (impact) {
    const key = String(impact).toUpperCase();
    const cfg = IMPACT_CONFIG[key] || {
      label: impact,
      icon: "•",
      variant: "neutral",
    };
    return (
      <span
        title={title || cfg.label}
        className={`badge badge-${cfg.variant} badge-${size} ${className}`}
      >
        <span className="badge-icon">{icon || cfg.icon}</span>
        <span>{children || cfg.label}</span>
      </span>
    );
  }

  return (
    <span
      title={title}
      className={`badge badge-${variant} badge-${size} ${className}`}
    >
      {icon && <span className="badge-icon">{icon}</span>}
      <span>{children}</span>
    </span>
  );
}

