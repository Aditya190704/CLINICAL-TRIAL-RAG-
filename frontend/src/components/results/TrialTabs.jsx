import React from "react";
import Badge from "../ui/Badge";
import { formatScore } from "../../utils/formatters";

/**
 * Modern Tabs selector for candidate clinical trials.
 */
export default function TrialTabs({
  matches = [],
  activeTab = 0,
  onSelectTab,
}) {
  if (!Array.isArray(matches) || matches.length === 0) return null;

  return (
    <div className="trial-tabs-container" role="tablist" aria-label="Clinical Trial Shortlist">
      {matches.map((trial, index) => {
        const isActive = index === activeTab;
        const rank = trial.rank ?? index + 1;
        const score = formatScore(trial.relevance_score);

        return (
          <button
            key={trial.nct_id || index}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`trial-tab-item ${isActive ? "trial-tab-active" : ""}`}
            onClick={() => onSelectTab(index)}
          >
            <div className="tab-top-row">
              <span className="tab-rank">#{rank}</span>
              <span className="tab-score-pill">{score} Similarity</span>
              <Badge verdict={trial.verdict} size="sm" />
            </div>

            <div className="tab-title-text" title={trial.title}>
              {trial.title || "Untitled Trial"}
            </div>

            <div className="tab-bottom-row">
              <span className="tab-nct-id">{trial.nct_id}</span>
              {trial.phases && trial.phases.length > 0 && (
                <span className="tab-phase">{trial.phases.join(", ")}</span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

