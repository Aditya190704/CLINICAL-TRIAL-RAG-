import React, { useState } from "react";
import Badge from "../ui/Badge";
import Button from "../ui/Button";
import CriteriaSection from "./CriteriaSection";
import PassagesSection from "./PassagesSection";
import { formatScore } from "../../utils/formatters";

/**
 * Deep-dive detail card for the currently selected clinical trial match.
 */
export default function TrialDetailView({
  match,
  onOpenChat,
  onCopyNotice,
}) {
  const [activeTab, setActiveTab] = useState("criteria"); // 'criteria' | 'passages'
  const [copiedId, setCopiedId] = useState(false);

  if (!match) {
    return (
      <div className="trial-detail-empty">
        <p>Select a trial above to inspect detailed eligibility evidence.</p>
      </div>
    );
  }

  const {
    nct_id,
    title,
    url,
    status = "RECRUITING",
    phases = [],
    conditions = [],
    sponsor,
    locations = [],
    relevance_score,
    verdict = "POSSIBLY_ELIGIBLE",
    summary = "",
    criteria = [],
    passages = [],
    dropped_unverified = 0,
  } = match;

  const officialUrl =
    url || (nct_id ? `https://clinicaltrials.gov/study/${nct_id}` : "");

  const handleCopyNctId = () => {
    if (nct_id) {
      navigator.clipboard.writeText(nct_id).catch(() => {});
      setCopiedId(true);
      if (onCopyNotice) onCopyNotice(`Copied ${nct_id} to clipboard`);
      setTimeout(() => setCopiedId(false), 2000);
    }
  };

  const handleCopyTrialSummary = () => {
    const text = [
      `Trial: ${title} (${nct_id})`,
      `Verdict: ${verdict}`,
      `Relevance: ${formatScore(relevance_score)}`,
      `Status: ${status}`,
      summary ? `Summary: ${summary}` : "",
      officialUrl ? `URL: ${officialUrl}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    navigator.clipboard.writeText(text).catch(() => {});
    if (onCopyNotice) onCopyNotice("Trial summary copied to clipboard");
  };

  // Metrics tallies
  const metCount = criteria.filter((c) => c.impact === "SUPPORTS").length;
  const blocksCount = criteria.filter((c) => c.impact === "BLOCKS").length;
  const unknownCount = criteria.filter(
    (c) => c.impact === "UNKNOWN" || !c.impact
  ).length;

  return (
    <article className="trial-detail-card" aria-labelledby="trial-detail-heading">
      {/* ── Top Header ── */}
      <div className="trial-detail-top">
        <div className="trial-header-main">
          <div className="trial-meta-pills">
            <button
              type="button"
              className="nct-id-button"
              onClick={handleCopyNctId}
              title="Click to copy NCT identifier"
            >
              <span>{nct_id}</span>
              <span className="copy-icon">{copiedId ? "✓" : "📋"}</span>
            </button>

            <span className="status-pill status-pill-active">{status}</span>

            {phases.length > 0 && (
              <span className="phase-pill">{phases.join(", ")}</span>
            )}

            {sponsor && <span className="sponsor-pill">{sponsor}</span>}
          </div>

          <h2 id="trial-detail-heading" className="trial-title">
            {title}
          </h2>

          {conditions.length > 0 && (
            <div className="conditions-row">
              {conditions.slice(0, 5).map((cond, i) => (
                <span key={i} className="condition-tag">
                  {cond}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* ── Action bar ── */}
        <div className="trial-header-actions">
          {officialUrl && (
            <a
              href={officialUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-outline btn-sm"
              title="View on ClinicalTrials.gov"
            >
              Study Record ↗
            </a>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopyTrialSummary}
            icon="📋"
            title="Copy trial details to clipboard"
          >
            Copy
          </Button>

          {onOpenChat && (
            <Button
              variant="primary"
              size="sm"
              onClick={onOpenChat}
              icon="💬"
              title="Ask AI follow-up questions about this trial"
            >
              Ask AI About Trial
            </Button>
          )}
        </div>
      </div>

      {/* ── Evaluation Metrics Grid ── */}
      <div className="trial-metrics-grid">
        {/* Verdict Box */}
        <div className={`verdict-summary-card verdict-${verdict}`}>
          <div className="verdict-card-top">
            <span className="verdict-card-label">ASSIGNED VERDICT</span>
            <Badge verdict={verdict} size="md" />
          </div>
          <p className="verdict-summary-text">
            {verdict === "ELIGIBLE"
              ? "All assessed criteria support this patient case with no blocking exclusions found."
              : verdict === "EXCLUDED"
              ? "At least one evaluated criterion blocks this patient based on documented evidence."
              : "No definitive blockers identified, but certain required clinical criteria remain unknown."}
          </p>
        </div>

        {/* Semantic Topic Match */}
        <div className="metric-box">
          <div className="metric-box-header">
            <span className="metric-label">Semantic Topic Match</span>
            <span className="metric-score-value">
              {formatScore(relevance_score)}
            </span>
          </div>
          <div className="metric-progress-track">
            <div
              className="metric-progress-fill"
              style={{
                width: `${Math.round(
                  Math.max(0, Math.min(1, relevance_score || 0)) * 100
                )}%`,
              }}
            />
          </div>
          <span className="metric-caption">
            Similarity of patient narrative to trial text. Not an eligibility score.
          </span>
        </div>

        {/* Criteria Tallies */}
        <div className="metric-box tallies-box">
          <span className="metric-label">Criteria Evaluated</span>
          <div className="tallies-grid">
            <div className="tally-item tally-met">
              <span className="tally-count">{metCount}</span>
              <span className="tally-name">Met</span>
            </div>
            <div className="tally-item tally-blocks">
              <span className="tally-count">{blocksCount}</span>
              <span className="tally-name">Blocks</span>
            </div>
            <div className="tally-item tally-unknown">
              <span className="tally-count">{unknownCount}</span>
              <span className="tally-name">Needs Info</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── AI Summary Box ── */}
      {summary && (
        <div className="trial-ai-summary">
          <div className="summary-title-row">
            <span className="summary-icon">✨</span>
            <span className="summary-heading">Clinical Assessment Summary</span>
          </div>
          <p className="summary-body">{summary}</p>
        </div>
      )}

      {/* ── Tabs for Criteria vs Retrieved Passages ── */}
      <div className="trial-detail-tabs-bar">
        <div className="detail-tabs">
          <button
            type="button"
            className={`detail-tab-btn ${
              activeTab === "criteria" ? "detail-tab-active" : ""
            }`}
            onClick={() => setActiveTab("criteria")}
          >
            Eligibility Criteria ({criteria.length})
          </button>
          <button
            type="button"
            className={`detail-tab-btn ${
              activeTab === "passages" ? "detail-tab-active" : ""
            }`}
            onClick={() => setActiveTab("passages")}
          >
            Retrieved Passages ({passages.length})
          </button>
        </div>

        {dropped_unverified > 0 && (
          <span className="unverified-badge" title="Statements dropped because verbatim quotes were not found in original source">
            ⚠ {dropped_unverified} unverified AI statement{dropped_unverified > 1 ? "s" : ""} discarded
          </span>
        )}
      </div>

      {/* ── Content View ── */}
      <div className="trial-detail-content">
        {activeTab === "criteria" ? (
          <CriteriaSection criteria={criteria} />
        ) : (
          <PassagesSection
            passages={passages}
            nctId={nct_id}
            officialUrl={officialUrl}
          />
        )}
      </div>

      {locations.length > 0 && (
        <div className="trial-locations-footer">
          <span className="locations-label">Study Locations:</span>
          <span className="locations-text">
            {locations.slice(0, 3).join(" • ")}
            {locations.length > 3 && ` (+${locations.length - 3} more)`}
          </span>
        </div>
      )}
    </article>
  );
}

