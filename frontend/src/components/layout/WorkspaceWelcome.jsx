import React from "react";

function greetingForHour(hour) {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function WorkspaceWelcome({
  displayName,
  healthStatus,
  trialCount,
  sessionCount,
  onStartSearch,
  onLoadSample,
  actionsDisabled = false,
}) {
  const now = new Date();
  const greeting = greetingForHour(now.getHours());
  const dateLabel = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(now);
  const serviceOnline = healthStatus === "online";
  const statusLabel = serviceOnline
    ? "Trial search is ready"
    : healthStatus === "checking"
      ? "Checking trial service"
      : "Trial service is unavailable";

  return (
    <section className="workspace-welcome" aria-labelledby="workspace-welcome-title">
      <div className="welcome-copy">
        <div className="welcome-eyebrow">
          <span className="welcome-eyebrow-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M12 2.7 20 6v5.2c0 5-3.4 8.3-8 10.1-4.6-1.8-8-5.1-8-10.1V6l8-3.3Z" stroke="currentColor" strokeWidth="1.7" />
              <path d="M12 7.3v9.4M7.3 12h9.4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </span>
          <span>Clinical research workspace</span>
          <span className="welcome-date">{dateLabel}</span>
        </div>
        <h1 id="workspace-welcome-title">{greeting}, {displayName}</h1>
        <p className="welcome-description">
          Find relevant clinical trials, review the evidence behind each match, and pick up where you left off.
        </p>
        <div className="welcome-actions">
          <button type="button" className="welcome-primary-action" onClick={onStartSearch} disabled={actionsDisabled}>
            <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M8.8 14.5a5.7 5.7 0 1 1 4-1.6M13 13l4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              <path d="M8.8 6.2v4.8M6.4 8.6h4.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            Start a patient search
          </button>
          <button type="button" className="welcome-secondary-action" onClick={onLoadSample} disabled={actionsDisabled}>
            Explore with a sample case
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>

      <div className="welcome-overview" aria-label="Workspace status">
        <div className="welcome-overview-heading">
          <span className={`welcome-status-dot ${serviceOnline ? "is-online" : healthStatus === "checking" ? "is-checking" : "is-offline"}`} />
          <span>{statusLabel}</span>
        </div>
        <div className="welcome-stat-grid">
          <div className="welcome-stat">
            <span className="welcome-stat-icon welcome-stat-icon-blue" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><circle cx="10.8" cy="10.8" r="6.5" stroke="currentColor" strokeWidth="1.8" /><path d="m16 16 4.2 4.2M8.2 10.8h5.2M10.8 8.2v5.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
            </span>
            <span className="welcome-stat-value">{trialCount > 0 ? Number(trialCount).toLocaleString() : "—"}</span>
            <span className="welcome-stat-label">indexed trials</span>
          </div>
          <div className="welcome-stat">
            <span className="welcome-stat-icon welcome-stat-icon-green" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><path d="M5 19V7.5A2.5 2.5 0 0 1 7.5 5h9A2.5 2.5 0 0 1 19 7.5V19H5Z" stroke="currentColor" strokeWidth="1.7" /><path d="M8 9h8M8 12.5h5M8 16h3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
            </span>
            <span className="welcome-stat-value">{Number(sessionCount || 0).toLocaleString()}</span>
            <span className="welcome-stat-label">saved sessions</span>
          </div>
        </div>
        <div className="welcome-trust-note">
          <span aria-hidden="true">✓</span>
          <span>Evidence-linked results for clinical review</span>
        </div>
      </div>
    </section>
  );
}
