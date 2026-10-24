import React from "react";
import { formatRelativeTime, truncate } from "../../utils/formatters";

/**
 * Individual session item in the sidebar.
 */
export default function SessionItem({
  session,
  isActive,
  onSelect,
  onRename,
  onDelete,
}) {
  const { id, title, patientCase, data, updatedAt, createdAt } = session;

  const matches = data?.matches || [];
  const matchCount = matches.length;
  const eligibleCount = matches.filter(
    (m) => m.verdict === "ELIGIBLE" || m.verdict === "LIKELY ELIGIBLE"
  ).length;

  const snippet = patientCase ? truncate(patientCase, 85) : "Ready for a new clinical search";

  return (
    <div
      className={`session-item ${isActive ? "session-item-active" : ""}`}
      onClick={() => onSelect(id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(id);
        }
      }}
      aria-current={isActive ? "true" : undefined}
    >
      <div className="session-item-header">
        <div className="session-item-title-group">
          {isActive && <span className="active-dot" title="Active session" />}
          <span className="session-item-title" title={title}>
            {title || "Untitled Session"}
          </span>
        </div>

        <div className="session-item-actions" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="session-action-btn"
            title="Rename session"
            onClick={() => onRename(session)}
            aria-label={`Rename ${title}`}
          >
            ✎
          </button>
          <button
            type="button"
            className="session-action-btn session-action-danger"
            title="Delete session"
            onClick={() => onDelete(session)}
            aria-label={`Delete ${title}`}
          >
            🗑
          </button>
        </div>
      </div>

      <p className="session-item-snippet">{snippet}</p>

      <div className="session-item-meta">
        <span className="session-time">
          {formatRelativeTime(updatedAt || createdAt)}
        </span>

        {matchCount > 0 ? (
          <span className="session-badge session-badge-matched">
            {matchCount} {matchCount === 1 ? "trial" : "trials"}
            {eligibleCount > 0 && ` • ${eligibleCount} eligible`}
          </span>
        ) : patientCase ? (
          <span className="session-badge session-badge-draft">Ready to match</span>
        ) : (
          <span className="session-badge session-badge-empty">Ready to search</span>
        )}
      </div>
    </div>
  );
}

