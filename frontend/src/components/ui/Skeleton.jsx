import React from "react";

export function SkeletonLine({ width = "100%", height = "14px", className = "" }) {
  return (
    <div
      className={`skeleton-line ${className}`}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <div className="skeleton-card-header">
        <SkeletonLine width="25%" height="20px" />
        <SkeletonLine width="15%" height="20px" />
      </div>
      <div className="skeleton-card-body">
        <SkeletonLine width="90%" height="24px" />
        <SkeletonLine width="60%" height="16px" />
        <div style={{ marginTop: "16px" }}>
          <SkeletonLine width="100%" height="14px" />
          <SkeletonLine width="95%" height="14px" style={{ marginTop: "8px" }} />
          <SkeletonLine width="80%" height="14px" style={{ marginTop: "8px" }} />
        </div>
      </div>
    </div>
  );
}

export default {
  Line: SkeletonLine,
  Card: SkeletonCard,
};

