import React from "react";

/**
 * Toast notification component.
 */
export default function Toast({ toast, onDismiss }) {
  if (!toast) return null;

  const { message, type = "info" } = toast;

  const ICONS = {
    success: "✓",
    error: "⚠",
    warning: "!",
    info: "ⓘ",
  };

  return (
    <div className={`toast toast-${type}`} role="status" aria-live="polite">
      <span className="toast-icon">{ICONS[type] || "•"}</span>
      <span className="toast-message">{message}</span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="toast-close"
          aria-label="Dismiss notification"
        >
          ✕
        </button>
      )}
    </div>
  );
}

