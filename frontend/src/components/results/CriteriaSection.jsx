import React, { useState, useMemo } from "react";
import Badge from "../ui/Badge";
import { deduplicateCriteria } from "../../utils/deduplication";

/**
 * Structured Eligibility Criteria Section.
 * Organizes criteria into Met, Blocking, and Could not assess categories with verbatim quotes.
 */
export default function CriteriaSection({ criteria = [] }) {
  const [filter, setFilter] = useState("ALL");

  // Clean and deduplicate criteria
  const cleanCriteria = useMemo(() => {
    return deduplicateCriteria(criteria);
  }, [criteria]);

  const metList = useMemo(
    () => cleanCriteria.filter((c) => c.impact === "SUPPORTS"),
    [cleanCriteria]
  );
  const blocksList = useMemo(
    () => cleanCriteria.filter((c) => c.impact === "BLOCKS"),
    [cleanCriteria]
  );
  const unknownList = useMemo(
    () =>
      cleanCriteria.filter(
        (c) => c.impact === "UNKNOWN" || !c.impact
      ),
    [cleanCriteria]
  );

  const displayedList = useMemo(() => {
    switch (filter) {
      case "SUPPORTS":
        return metList;
      case "BLOCKS":
        return blocksList;
      case "UNKNOWN":
        return unknownList;
      default:
        return cleanCriteria;
    }
  }, [filter, cleanCriteria, metList, blocksList, unknownList]);

  if (cleanCriteria.length === 0) {
    return (
      <div className="criteria-empty-state">
        <p className="empty-state-text">
          No individual criterion quotes were extracted for this trial.
        </p>
      </div>
    );
  }

  return (
    <div className="criteria-section">
      <div className="criteria-header">
        <div className="criteria-filters" role="tablist" aria-label="Criteria impact filters">
          <button
            type="button"
            className={`filter-btn ${filter === "ALL" ? "filter-active" : ""}`}
            onClick={() => setFilter("ALL")}
          >
            All Criteria ({cleanCriteria.length})
          </button>
          <button
            type="button"
            className={`filter-btn filter-met ${filter === "SUPPORTS" ? "filter-active" : ""}`}
            onClick={() => setFilter("SUPPORTS")}
          >
            ✓ Met ({metList.length})
          </button>
          <button
            type="button"
            className={`filter-btn filter-blocks ${filter === "BLOCKS" ? "filter-active" : ""}`}
            onClick={() => setFilter("BLOCKS")}
          >
            ✕ Blocking ({blocksList.length})
          </button>
          <button
            type="button"
            className={`filter-btn filter-unknown ${filter === "UNKNOWN" ? "filter-active" : ""}`}
            onClick={() => setFilter("UNKNOWN")}
          >
            ? Could not assess ({unknownList.length})
          </button>
        </div>
      </div>

      <div className="criteria-list">
        {displayedList.length === 0 ? (
          <div className="criteria-no-matches">
            <p>No criteria match the selected filter ({filter}).</p>
          </div>
        ) : (
          displayedList.map((item, index) => {
            const quote = item.criterion_quote || item.criterion || item.text || "";
            const patientQuote = item.patient_evidence || item.patient_evidence_quote || "";
            const explanation = item.explanation || "";
            const type = item.criterion_type || "CRITERION";
            const source = item.source === "STRUCTURED" ? "Registry Field" : "Trial Text";

            return (
              <div key={index} className={`criterion-card criterion-card-${item.impact || "UNKNOWN"}`}>
                <div className="criterion-top-bar">
                  <div className="criterion-meta-left">
                    <span className="criterion-type-pill">{type}</span>
                    <span className="criterion-source-tag">{source}</span>
                  </div>
                  <Badge impact={item.impact} size="sm" />
                </div>

                {/* Trial Registry Rule Quote */}
                <div className="quote-block quote-trial">
                  <span className="quote-label">Trial Criterion:</span>
                  <p className="quote-text">"{quote}"</p>
                </div>

                {/* Patient Evidence Quote (when present) */}
                {patientQuote && (
                  <div className="quote-block quote-patient">
                    <span className="quote-label">Patient Case Evidence:</span>
                    <p className="quote-text">"{patientQuote}"</p>
                  </div>
                )}

                {/* Clinical Reasoning / Explanation */}
                {explanation && (
                  <div className="criterion-explanation">
                    <span className="explanation-label">Assessment:</span>
                    <p className="explanation-text">{explanation}</p>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

