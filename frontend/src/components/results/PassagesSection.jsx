import React, { useMemo } from "react";
import { deduplicatePassages } from "../../utils/deduplication";

/**
 * Retrieved Trial Passages & Citations view.
 */
export default function PassagesSection({
  passages = [],
  nctId = "",
  officialUrl = "",
}) {
  const cleanPassages = useMemo(() => {
    return deduplicatePassages(passages);
  }, [passages]);

  if (cleanPassages.length === 0) {
    return (
      <div className="passages-empty-state">
        <p>No raw text passages were returned for this trial.</p>
        {officialUrl && (
          <a
            href={officialUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="external-study-link"
          >
            Open full study record on ClinicalTrials.gov ↗
          </a>
        )}
      </div>
    );
  }

  return (
    <div className="passages-section">
      <div className="passages-header">
        <p className="passages-description">
          Retrieved evidence chunks from the official clinical trial study record in BigQuery.
        </p>
      </div>

      <div className="passages-grid">
        {cleanPassages.map((item, index) => {
          const type = (item.chunk_type || "Passage").toUpperCase();
          const text = item.text || "";

          return (
            <div key={index} className="passage-card">
              <div className="passage-card-header">
                <span className="passage-type-badge">{type}</span>
                {officialUrl && (
                  <a
                    href={officialUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="passage-study-link"
                    title="View on ClinicalTrials.gov"
                  >
                    {nctId} ↗
                  </a>
                )}
              </div>
              <p className="passage-text">{text}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

