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
}) {
  return (
    <header className="app-header">
      <div className="header-left">
        <div className="header-brand">
          <div className="header-logo" aria-hidden="true">
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
              healthStatus === "online" ? "status-online" : "status-offline"
            }`}
          />
          <span className="status-text">
            {healthStatus === "online"
              ? `${trialCount} Trials Indexed`
              : "Connecting to API..."}
          </span>
        </div>
      </div>

      <div className="header-right">
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

