import React, { useMemo, useState } from "react";
import Badge from "../ui/Badge";
import { deduplicateCriteria } from "../../utils/deduplication";

const FILTERS = [
  { id: "ALL", label: "All criteria" },
  { id: "SUPPORTS", label: "Met" },
  { id: "BLOCKS", label: "Not met" },
  { id: "UNKNOWN", label: "Could not assess" },
];

/** Render quote-verified criteria as a readable, filterable evidence table. */
export default function CriteriaSection({ criteria = [] }) {
  const [filter, setFilter] = useState("ALL");
  const cleanCriteria = useMemo(() => deduplicateCriteria(criteria), [criteria]);
  const counts = useMemo(() => ({
    ALL: cleanCriteria.length,
    SUPPORTS: cleanCriteria.filter((item) => item.impact === "SUPPORTS").length,
    BLOCKS: cleanCriteria.filter((item) => item.impact === "BLOCKS").length,
    UNKNOWN: cleanCriteria.filter((item) => item.impact === "UNKNOWN" || !item.impact).length,
  }), [cleanCriteria]);
  const displayed = filter === "ALL"
    ? cleanCriteria
    : cleanCriteria.filter((item) => filter === "UNKNOWN"
      ? item.impact === "UNKNOWN" || !item.impact
      : item.impact === filter);

  if (!cleanCriteria.length) {
    return <div className="criteria-empty-state"><p className="empty-state-text">No individual criterion quotes were extracted for this trial.</p></div>;
  }

  return (
    <div className="criteria-section">
      <div className="criteria-header">
        <div className="criteria-filters" role="group" aria-label="Filter criteria by assessment">
          {FILTERS.map((item) => (
            <button key={item.id} type="button" aria-pressed={filter === item.id}
              className={`filter-btn filter-${item.id.toLowerCase()} ${filter === item.id ? "filter-active" : ""}`}
              onClick={() => setFilter(item.id)}>
              {item.label} <span>{counts[item.id]}</span>
            </button>
          ))}
        </div>
      </div>

      {!displayed.length ? (
        <div className="criteria-no-matches"><p>No criteria match this filter.</p></div>
      ) : (
        <div className="criteria-table-wrap">
          <table className="criteria-table">
            <thead><tr><th scope="col">Trial requirement</th><th scope="col">Patient evidence</th><th scope="col">Assessment</th><th scope="col">Status</th></tr></thead>
            <tbody>{displayed.map((item, index) => {
              const requirement = item.criterion_quote || item.criterion || item.text || "Criterion text unavailable.";
              const evidence = item.patient_evidence || item.patient_evidence_quote || "";
              const source = item.source === "STRUCTURED" ? "Registry field" : "Trial text";
              return (
                <tr key={`${item.criterion_type || "criterion"}-${index}`} className={`criterion-row criterion-row-${item.impact || "UNKNOWN"}`}>
                  <td data-label="Trial requirement">
                    <div className="criterion-table-meta"><span className="criterion-type-pill">{item.criterion_type || "CRITERION"}</span><span className="criterion-source-tag">{source}</span></div>
                    <p className="criterion-table-quote">“{requirement}”</p>
                  </td>
                  <td data-label="Patient evidence">{evidence ? <blockquote className="criterion-patient-evidence">“{evidence}”</blockquote> : <span className="criterion-missing-evidence">Not provided in the case</span>}</td>
                  <td data-label="Assessment"><span className="criterion-assessment-text">{item.explanation || "No assessment explanation was returned."}</span></td>
                  <td data-label="Status"><Badge impact={item.impact} size="sm" /></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
