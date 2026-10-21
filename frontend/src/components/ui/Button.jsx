import React from "react";

/**
 * Reusable accessible Button component with multiple variants & sizes.
 */
export default function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  icon = null,
  iconRight = null,
  className = "",
  type = "button",
  onClick,
  title,
  ...props
}) {
  const isDisabled = disabled || loading;

  return (
    <button
      type={type}
      disabled={isDisabled}
      onClick={onClick}
      title={title}
      className={`btn btn-${variant} btn-${size} ${className}`}
      {...props}
    >
      {loading ? (
        <span className="btn-spinner" aria-hidden="true" />
      ) : icon ? (
        <span className="btn-icon-left">{icon}</span>
      ) : null}

      <span className="btn-label">{children}</span>

      {!loading && iconRight && (
        <span className="btn-icon-right">{iconRight}</span>
      )}
    </button>
  );
}

