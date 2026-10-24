import React from "react";
import Button from "../ui/Button";
import Icon from "../ui/Icon";

/** Branded product header with service status and account actions. */
export default function Header({
  healthStatus = "online",
  trialCount = 0,
  sessionCount = 0,
  isSidebarOpen,
  onToggleSidebar,
  onNewSession,
  hasAssessment = false,
  onOpenAssessment,
  displayName = "",
  onLogout,
}) {
  const initials = displayName.split(/\s+/).filter(Boolean).slice(0, 2)
    .map((part) => part[0].toUpperCase()).join("") || "CT";
  const serviceLabel = healthStatus === "online"
    ? trialCount ? `${trialCount.toLocaleString()} trials indexed` : "Trial search ready"
    : healthStatus === "checking" ? "Connecting to trial service" : "Trial service unavailable";

  return (
    <header className="app-header clinical-header">
      <div className="header-left clinical-header-brand">
        <div className="header-brand">
          <span className="header-logo" aria-hidden="true"><Icon name="shield" size={28} /></span>
          <div className="brand-text">
            <div className="brand-row">
              <h1 className="brand-title">Clinical Trial Matcher</h1>
              <span className="brand-badge">RESEARCH WORKSPACE</span>
            </div>
            <p className="brand-subtitle">Evidence-led clinical trial discovery</p>
          </div>
        </div>
      </div>

      <div className="header-center clinical-header-status" aria-live="polite">
        <div className="system-status-indicator" title="Clinical trial search service status">
          <span className={`status-pulse-dot ${healthStatus === "online" ? "status-online" : healthStatus === "checking" ? "status-checking" : "status-offline"}`} />
          <span className="status-copy"><strong>{serviceLabel}</strong><small>{healthStatus === "online" ? "Search services operational" : "Service status"}</small></span>
        </div>
      </div>

      <nav className="header-right clinical-header-actions" aria-label="Workspace actions">
        {displayName && (
          <div className="header-user-chip" title={`${displayName} · Clinical Technician`}>
            <span className="header-user-avatar" aria-hidden="true">{initials}</span>
            <span className="header-user-copy"><strong className="signed-in-label">{displayName}</strong><small>Clinical technician</small></span>
          </div>
        )}

        {hasAssessment && onOpenAssessment && (
          <Button variant="subtle" size="sm" onClick={onOpenAssessment}
            title="Open the clinical assessment summary" aria-label="Open clinical assessment summary"
            icon={<Icon name="clipboard" size={16} />} className="header-assessment-action">
            Assessment
          </Button>
        )}

        <Button variant="outline" size="sm" onClick={onNewSession}
          title="Start a new clinical trial search" icon={<span className="header-plus-icon" aria-hidden="true">+</span>}
          className="header-new-session">
          New search
        </Button>

        <button type="button" onClick={onToggleSidebar}
          className={`sidebar-toggle-btn ${isSidebarOpen ? "sidebar-toggle-active" : ""}`}
          title={isSidebarOpen ? "Collapse session history" : "Open session history"}
          aria-label={isSidebarOpen ? "Collapse saved sessions" : "Open saved sessions"}
          aria-expanded={isSidebarOpen}>
          <Icon name="folder" size={17} className="toggle-icon" />
          <span className="toggle-label">My sessions</span>
          {sessionCount > 0 && <span className="toggle-badge">{sessionCount}</span>}
        </button>

        {onLogout && <Button variant="ghost" size="sm" onClick={onLogout} title="Sign out of your account" aria-label="Sign out" icon={<Icon name="logout" size={16} />} className="header-signout">Sign out</Button>}
      </nav>
    </header>
  );
}
