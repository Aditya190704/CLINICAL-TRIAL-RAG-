import React from "react";
import Button from "../ui/Button";

/**
 * Top Navigation Bar with Branding, Health Status, and Actions.
 */
export default function Header({
  healthStatus = "online",
  trialCount = 484,
  sessionCount = 1,
  isSidebarOpen,
  onToggleSidebar,
  onNewSession,
  onLoadSample,
  hasResults = false,
  onOpenChat,
  hasAssessment = false,
  onOpenAssessment,
  displayName = "",
  onLogout,
}) {
  const initials = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("") || "CT";

  return (
    <header className="app-header">
      <div className="header-left">
        <div className="header-brand">
          <div className="header-logo" aria-hidden="true">
            <svg className="logo-medical-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path d="M16 2.8 27.2 9v8.1c0 6.5-4.7 10.4-11.2 12.1C9.5 27.5 4.8 23.6 4.8 17.1V9L16 2.8Z" stroke="currentColor" strokeWidth="1.8" />
              <path d="M16 10v12M10 16h12" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
            </svg>
            <span className="logo-symbol">✚</span>
          </div>
          <div className="brand-text">
            <div className="brand-row">
              <h1 className="brand-title">Clinical Trial Matcher</h1>
              <span className="brand-badge">Decision Support</span>
            </div>
            <p className="brand-subtitle">
              Evidence-guided clinical trial retrieval & eligibility reasoning
            </p>
          </div>
        </div>
      </div>

      <div className="header-center">
        <div className="system-status-indicator" title="Backend operational status">
          <span
            className={`status-pulse-dot ${
              healthStatus === "online" ? "status-online" : healthStatus === "checking" ? "status-checking" : "status-offline"
            }`}
          />
          <span className="status-text">
            {healthStatus === "online"
              ? (trialCount ? `${trialCount.toLocaleString()} Trials Indexed` : "Trial search online")
              : healthStatus === "checking"
                ? "Connecting to trial service…"
                : "Trial service unavailable"}
          </span>
        </div>
      </div>

      <div className="header-right">
        {displayName && (
          <div className="header-user-chip" title={`${displayName} · Clinical Technician`}>
            <span className="header-user-avatar" aria-hidden="true">{initials}</span>
            <span className="signed-in-label">{displayName}</span>
          </div>
        )}
        {hasAssessment && onOpenAssessment && (
          <Button
            variant="subtle"
            size="sm"
            onClick={onOpenAssessment}
            title="Open the clinical assessment summary"
            aria-label="Open clinical assessment summary"
            icon={<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M5 2.8h7l3 3v11.4H5V2.8Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M12 2.8v3.4h3M7.5 9h5M7.5 12h5M7.5 15h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>}
          >
            Assessment Summary
          </Button>
        )}
        {onLoadSample && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onLoadSample}
            title="Load an anonymized stage IIIB NSCLC patient case"
            icon="📄"
            className="hidden-mobile"
          >
            Load Sample
          </Button>
        )}

        {hasResults && onOpenChat && (
          <Button
            variant="subtle"
            size="sm"
            onClick={onOpenChat}
            title="Ask questions about retrieved trials"
            icon="💬"
          >
            Ask AI
          </Button>
        )}

        <Button
          variant="outline"
          size="sm"
          onClick={onNewSession}
          title="Clear and start a new matching session"
          icon="+"
        >
          New Match
        </Button>

        {onLogout && (
          <Button variant="ghost" size="sm" onClick={onLogout} title="Sign out and clear this user's workspace">
            Sign out
          </Button>
        )}

        {/* Sidebar Toggle Button with Session Count Badge */}
        <button
          type="button"
          onClick={onToggleSidebar}
          className={`sidebar-toggle-btn ${isSidebarOpen ? "sidebar-toggle-active" : ""}`}
          title={isSidebarOpen ? "Collapse session sidebar" : "Open session history"}
          aria-label={isSidebarOpen ? "Collapse session sidebar" : "Open session history"}
          aria-expanded={isSidebarOpen}
        >
          <span className="toggle-icon">📂</span>
          <span className="toggle-label">Sessions</span>
          {sessionCount > 0 && (
            <span className="toggle-badge">{sessionCount}</span>
          )}
        </button>
      </div>
    </header>
  );
}

