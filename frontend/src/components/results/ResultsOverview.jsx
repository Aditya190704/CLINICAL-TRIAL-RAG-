import React, { useState } from "react";
import Badge from "../ui/Badge";
import Button from "../ui/Button";

/**
 * Results Summary Bar with key counts, latency, and copy action.
 */
export default function ResultsOverview({
  data,
  onCopySummary,
  onOpenChat,
}) {
  const [copied, setCopied] = useState(false);

  if (!data || !Array.isArray(data.matches)) return null;

  const matches = data.matches;
  const total = matches.length;
  const reviewRequired = matches.filter(
    (m) => m.verdict === "ELIGIBLE" || m.verdict === "LIKELY ELIGIBLE"
  ).length;
  const possible = matches.filter(
    (m) =>
      m.verdict === "POSSIBLY_ELIGIBLE" ||
      m.verdict === "POSSIBLY ELIGIBLE"
  ).length;
  const couldNotAssess = matches.filter((m) => m.verdict === "COULD_NOT_ASSESS").length;

  const handleCopy = () => {
    if (onCopySummary) {
      onCopySummary();
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="results-overview-bar">
      <div className="overview-stats">
        <div className="stat-item">
          <span className="stat-label">Candidate Trials</span>
          <span className="stat-value">{total}</span>
        </div>

        <div className="stat-divider" />

        <div className="stat-item">
          <span className="stat-label">Could Not Assess</span>
          <span className="stat-value">{couldNotAssess}</span>
        </div>

        <div className="stat-divider" />

        <div className="stat-item">
          <span className="stat-label">Requires Clinical Review</span>
          <span className="stat-value">{reviewRequired}</span>
        </div>

        <div className="stat-divider" />

        <div className="stat-item">
          <span className="stat-label">Possibly Eligible</span>
          <span className="stat-value text-warning">{possible}</span>
        </div>

        {data.latency_seconds > 0 && (
          <>
            <div className="stat-divider" />
            <div className="stat-item stat-latency">
              <span className="stat-label">Latency</span>
              <span className="stat-value-sm">{data.latency_seconds}s</span>
            </div>
          </>
        )}
      </div>

      <div className="overview-actions">
        {onOpenChat && (
          <Button
            variant="subtle"
            size="sm"
            onClick={onOpenChat}
            icon="💬"
            title="Ask questions about these trial candidates"
          >
            Ask AI Assistant
          </Button>
        )}

        {onCopySummary && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleCopy}
            icon={copied ? "✓" : "📋"}
            title="Copy match results summary to clipboard"
          >
            {copied ? "Copied" : "Copy Results"}
          </Button>
        )}
      </div>
    </div>
  );
}
