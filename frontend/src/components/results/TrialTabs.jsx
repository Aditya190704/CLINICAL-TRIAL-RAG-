import React from "react";
import Badge from "../ui/Badge";
import { formatScore } from "../../utils/formatters";

/** Three concise trial selectors with direct ClinicalTrials.gov citations. */
export default function TrialTabs({ matches = [], activeTab = 0, onSelectTab }) {
  if (!Array.isArray(matches) || matches.length === 0) return null;

  return (
    <div className="trial-tabs-container" role="group" aria-label="Top three candidate trials">
      {matches.slice(0, 3).map((trial, index) => {
        const isActive = index === activeTab;
        const rank = trial.rank ?? index + 1;
        const citationUrl = trial.url || `https://clinicaltrials.gov/study/${trial.nct_id}`;

        return (
          <article
            key={trial.nct_id || index}
            className={`trial-option ${isActive ? "trial-option-active" : ""}`}
          >
            <button
              type="button"
              aria-pressed={isActive}
              className="trial-tab-item"
              onClick={() => onSelectTab(index)}
            >
              <div className="tab-top-row">
                <span className="tab-rank">#{rank}</span>
                <Badge verdict={trial.verdict} size="sm" />
              </div>
              <span className="tab-title-text" title={trial.title}>
                {trial.title || "Untitled Trial"}
              </span>
              <div className="trial-card-facts">
                {trial.status && <span className="trial-card-status">{trial.status.replace(/_/g, " ")}</span>}
                {trial.phases?.length > 0 && <span>{trial.phases.join(", ")}</span>}
                {trial.conditions?.[0] && <span className="trial-card-condition">{trial.conditions[0]}</span>}
              </div>
              <div className="tab-bottom-row">
                <span className="tab-nct-id">{trial.nct_id}</span>
                <span className="tab-score-pill">{formatScore(trial.relevance_score)} topic similarity</span>
              </div>
              <span className="trial-card-view-action">View details <span aria-hidden="true">→</span></span>
            </button>
            <a
              className="tab-citation-link"
              href={citationUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Official ClinicalTrials.gov record for ${trial.nct_id}`}
            >
              Source: ClinicalTrials.gov ({trial.nct_id}) ↗
            </a>
          </article>
        );
      })}
    </div>
  );
}
