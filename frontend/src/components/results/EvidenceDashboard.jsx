import React, { useMemo } from "react";
import { downloadEvidenceReport } from "../../utils/evidenceReport";
import "./EvidenceDashboard.css";

const IMPACT_LABELS = {
  SUPPORTS: "Supported",
  BLOCKS: "Potential blockers",
  UNKNOWN: "Needs review",
};

function factList(profile = {}) {
  if (Array.isArray(profile.primary_conditions) && profile.primary_conditions.length) {
    return [...new Set(profile.primary_conditions.filter((fact) => typeof fact === "string" && fact.trim()))];
  }
  if (typeof profile.search_query === "string" && profile.search_query.trim()) {
    return [profile.search_query.trim()];
  }
  const facts = [
    ...(profile.key_findings || []),
    ...(profile.prior_treatments || []),
    ...(profile.current_medications || []),
  ];
  return [...new Set(facts.filter((fact) => typeof fact === "string" && fact.trim()))];
}

function countImpacts(matches) {
  return matches.reduce((counts, trial) => {
    (trial.criteria || []).forEach(({ impact }) => {
      if (impact in counts) counts[impact] += 1;
    });
    return counts;
  }, { SUPPORTS: 0, BLOCKS: 0, UNKNOWN: 0 });
}

/** Summarize search provenance and evidence completeness across the shortlist. */
export default function EvidenceDashboard({ data, sessionTitle }) {
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  const ruledOut = Array.isArray(data?.ruled_out_trials) ? data.ruled_out_trials : [];
  const basis = useMemo(() => factList(data?.patient_profile), [data?.patient_profile]);
  const counts = useMemo(() => countImpacts(matches), [matches]);
  const assessed = counts.SUPPORTS + counts.BLOCKS + counts.UNKNOWN;
  const completeness = assessed ? Math.round(((assessed - counts.UNKNOWN) / assessed) * 100) : 0;
  const privacyTrimmed = !data?.patient_profile && matches.length > 0;

  const handleDownload = () => {
    downloadEvidenceReport({ data, sessionTitle });
  };

  return (
    <section className="evidence-dashboard" aria-labelledby="evidence-dashboard-title">
      <div className="evidence-dashboard-header">
        <div>
          <span className="section-eyebrow">REVIEW TRACE</span>
          <h2 id="evidence-dashboard-title">Evidence at a glance</h2>
          <p>See what informed the search, where the assessment has support, and what still needs human review.</p>
        </div>
        <button type="button" className="evidence-report-button" onClick={handleDownload}>
          <span aria-hidden="true">↧</span> Download review report
        </button>
      </div>
      <p className="evidence-export-note">The report is generated on this device and may contain health-related evidence. Handle it according to your organization’s privacy practices.</p>

      <div className="evidence-dashboard-grid">
        <div className="evidence-basis-card">
          <div className="evidence-card-heading"><span className="evidence-step">01</span><h3>Why these trials surfaced</h3></div>
          <p className="evidence-card-caption">Primary conditions ground the initial search; a limited refinement may use other supported facts. Similarity ranks topic relevance only.</p>
          <div className="evidence-fact-chips">
            {basis.length ? basis.map((fact) => <span className="evidence-fact-chip" key={fact}>{fact}</span>) : <span className="evidence-muted">Search facts are unavailable in this saved result.</span>}
          </div>
          <div className="evidence-candidate-list">
            {matches.map((trial, index) => (
              <div className="evidence-candidate" key={trial.nct_id || index}>
                <span className="evidence-candidate-rank">{index + 1}</span>
                <div className="evidence-candidate-name"><strong>{trial.title}</strong><span>{trial.nct_id}</span></div>
                <span className="evidence-similarity" title="Retrieval similarity, not eligibility probability">{Math.round((trial.relevance_score || 0) * 100)}%<small>topic match</small></span>
              </div>
            ))}
            {!matches.length && <p className="evidence-muted">No candidate trials were returned for this search.</p>}
          </div>
          <p className="evidence-score-note">Topic similarity is not an eligibility score or probability.</p>
        </div>

        <div className="evidence-quality-card">
          <div className="evidence-card-heading"><span className="evidence-step">02</span><h3>Evidence coverage</h3></div>
          <p className="evidence-card-caption">Criterion checks across {matches.length} candidate{matches.length === 1 ? "" : "s"}. Open a trial below to inspect its source quotes.</p>
          <div className="evidence-coverage-meter" role="img" aria-label={`${completeness}% of criterion checks have supported or blocking evidence`}>
            <div className="evidence-coverage-fill" style={{ width: `${completeness}%` }} />
          </div>
          <div className="evidence-coverage-caption"><strong>{completeness}%</strong><span>{privacyTrimmed ? "checks assessed in saved summary" : "with evidence to review"}</span></div>
          <div className="evidence-impact-list">
            {Object.entries(IMPACT_LABELS).map(([impact, label]) => (
              <div className={`evidence-impact-row impact-${impact}`} key={impact}>
                <span className="evidence-impact-dot" /><span>{label}</span><strong>{counts[impact]}</strong>
              </div>
            ))}
          </div>
          <div className="evidence-followup">
            <h4>Review before acting</h4>
            <p>{privacyTrimmed ? "This saved summary omits patient case excerpts. Rerun matching to inspect the verified patient evidence alongside each trial quote." : counts.UNKNOWN ? `${counts.UNKNOWN} criterion check${counts.UNKNOWN === 1 ? "" : "s"} lack enough evidence. Missing case facts and conflicts are listed below.` : "Compare every supported finding with the official study record and confirm the details with the clinical team."}</p>
          </div>
        </div>
      </div>

      {ruledOut.length > 0 && (
        <div className="evidence-exclusions">
          <div><span className="section-eyebrow">SEPARATE REVIEW LIST</span><h3>Verified potential blockers</h3><p>These records had a blocking criterion in the assessed evidence. Confirm the quoted requirement against the official record.</p></div>
          <div className="evidence-exclusion-list">
            {ruledOut.map((trial) => (
              <article className="evidence-exclusion" key={trial.nct_id}>
                <div><strong>{trial.title}</strong><span>{trial.nct_id}</span><p>{trial.reason}</p></div>
                <a href={`https://clinicaltrials.gov/study/${encodeURIComponent(trial.nct_id)}`} target="_blank" rel="noopener noreferrer">Source ↗</a>
              </article>
            ))}
          </div>
        </div>
      )}

      {(data?.missing_key_facts?.length > 0 || data?.conflicting_facts?.length > 0) && (
        <div className="evidence-review-flags">
          {data?.missing_key_facts?.length > 0 && <div><h4>Information not provided</h4><ul>{data.missing_key_facts.map((item) => <li key={item}>{item}</li>)}</ul></div>}
          {data?.conflicting_facts?.length > 0 && <div><h4>Conflicts to resolve</h4><ul>{data.conflicting_facts.map((item) => <li key={item}>{item}</li>)}</ul></div>}
        </div>
      )}
    </section>
  );
}
