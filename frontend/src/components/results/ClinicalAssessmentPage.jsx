import React, { useState } from "react";
import CriteriaSection from "./CriteriaSection";
import PassagesSection from "./PassagesSection";
import { countCriteria, getAssessmentSummary } from "../../utils/assessment";

function AssessmentNotice({ data }) {
  const hasNotice = data?.emergency_notice
    || data?.missing_key_facts?.length
    || data?.conflicting_facts?.length;
  if (!hasNotice) return null;

  return (
    <section className={`result-safety-notice assessment-safety-notice ${data.emergency_notice ? "result-safety-urgent" : ""}`} role={data.emergency_notice ? "alert" : "status"}>
      {data.emergency_notice && <div><h3>Urgent safety notice</h3><p>{data.emergency_notice}</p></div>}
      {data.conflicting_facts?.length > 0 && <div><h3>Conflicting information to review</h3><ul>{data.conflicting_facts.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {data.missing_key_facts?.length > 0 && <div><h3>Information not provided</h3><ul>{data.missing_key_facts.map((item) => <li key={item}>{item}</li>)}</ul></div>}
    </section>
  );
}

export default function ClinicalAssessmentPage({ data, patientCase, sessionTitle, onBack }) {
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  const [selectedId, setSelectedId] = useState(matches[0]?.nct_id || "");
  const [activeTab, setActiveTab] = useState("criteria");
  // Keep the selected trial when possible; fall back to the first saved result.
  const selectedMatch = matches.find((match) => match.nct_id === selectedId) || matches[0];
  const criteria = selectedMatch?.criteria || [];
  const passages = selectedMatch?.passages || [];
  const counts = countCriteria(criteria);
  const officialUrl = selectedMatch?.url || (selectedMatch?.nct_id ? `https://clinicaltrials.gov/study/${selectedMatch.nct_id}` : "");

  return (
    <section className="clinical-assessment-page" aria-labelledby="clinical-assessment-title">
      <div className="assessment-page-toolbar">
        <button type="button" className="assessment-back-button" onClick={onBack}>
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m12.5 4.5-5.5 5.5 5.5 5.5M7.5 10h10" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Back to trial results
        </button>
        <span className="assessment-session-label" title={sessionTitle}>{sessionTitle || "Clinical trial review"}</span>
      </div>

      <header className="assessment-page-hero">
        <div className="assessment-hero-copy">
          <span className="section-eyebrow">CLINICAL REVIEW</span>
          <h1 id="clinical-assessment-title">Clinical Assessment Summary</h1>
          <p>Review each trial’s criteria, supporting patient evidence, and source passages.</p>
        </div>
      </header>

      <AssessmentNotice data={data} />

      {matches.length > 1 && (
        <nav className="assessment-trial-picker" aria-label="Choose a trial to assess">
          <span className="assessment-picker-label">TRIALS IN THIS SEARCH</span>
          <div className="assessment-trial-options">
            {matches.map((match, index) => (
              <button key={match.nct_id || index} type="button"
                className={`assessment-trial-option ${selectedMatch === match ? "is-selected" : ""}`}
                onClick={() => { setSelectedId(match.nct_id || ""); setActiveTab("criteria"); }}>
                <span className="assessment-trial-option-index">{index + 1}</span>
                <span className="assessment-trial-option-copy"><strong>{match.title || "Clinical trial"}</strong><small>{match.nct_id || "Trial ID unavailable"}</small></span>
              </button>
            ))}
          </div>
        </nav>
      )}

      {selectedMatch ? (
        <article className="assessment-focus-card">
          <header className="assessment-focus-header">
            <div>
              <div className="assessment-trial-meta">
                {selectedMatch.nct_id && <span>{selectedMatch.nct_id}</span>}
                {selectedMatch.status && <span>{selectedMatch.status}</span>}
                {selectedMatch.phases?.length > 0 && <span>{selectedMatch.phases.join(", ")}</span>}
              </div>
              <h2>{selectedMatch.title || "Clinical trial assessment"}</h2>
            </div>
            {officialUrl && <a className="assessment-official-link" href={officialUrl} target="_blank" rel="noopener noreferrer">Official study record ↗</a>}
          </header>

          <div className="assessment-summary-callout">
            <span className="assessment-summary-icon" aria-hidden="true">✦</span>
            <div><h3>Clinical Assessment Summary</h3><p>{getAssessmentSummary(selectedMatch, counts)}</p></div>
          </div>

          <div className="assessment-criteria-counts" aria-label="Eligibility criteria assessment counts">
            <div><strong>{criteria.length}</strong><span>All criteria</span></div>
            <div className="count-met"><strong>{counts.met}</strong><span>Met</span></div>
            <div className="count-blocking"><strong>{counts.blocking}</strong><span>Blocking</span></div>
            <div className="count-unknown"><strong>{counts.unknown}</strong><span>Could not assess</span></div>
          </div>

          <div className="assessment-tabbar" role="tablist" aria-label="Assessment evidence">
            <button type="button" role="tab" aria-selected={activeTab === "criteria"} className={activeTab === "criteria" ? "is-active" : ""} onClick={() => setActiveTab("criteria")}>Eligibility Criteria ({criteria.length})</button>
            <button type="button" role="tab" aria-selected={activeTab === "passages"} className={activeTab === "passages" ? "is-active" : ""} onClick={() => setActiveTab("passages")}>Retrieved Passages ({passages.length})</button>
          </div>

          <div className="assessment-evidence-panel" role="tabpanel">
            {activeTab === "criteria"
              ? <CriteriaSection criteria={criteria} />
              : <PassagesSection passages={passages} nctId={selectedMatch.nct_id || ""} officialUrl={officialUrl} />}
          </div>

          {selectedMatch.locations?.length > 0 && (
            <footer className="assessment-locations"><strong>Study locations</strong><span>{selectedMatch.locations.join(" · ")}</span></footer>
          )}
        </article>
      ) : (
        <div className="assessment-no-results"><h2>No matched trials to assess</h2><p>Run a trial search to see eligibility criteria and evidence here.</p></div>
      )}

      {patientCase && <details className="assessment-case-details"><summary>View original patient case</summary><p>{patientCase}</p></details>}
      <p className="assessment-page-disclaimer">
        This tool provides research assistance, not a medical diagnosis or treatment recommendation. Trial results are preliminary and do not establish eligibility. A qualified clinical team must review the official criteria and confirm any decision.
      </p>
    </section>
  );
}
