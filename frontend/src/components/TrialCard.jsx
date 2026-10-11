import { useState } from "react";

const VERDICT = {
  ELIGIBLE: {
    label: "Likely eligible", icon: "✓",
    text: "No blocking criteria were found, and every assessed criterion is supported by the case.",
  },
  POSSIBLY_ELIGIBLE: {
    label: "Possibly eligible", icon: "!",
    text: "No blocking criteria were found, but some information is missing. Confirm the open items below.",
  },
  EXCLUDED: {
    label: "Excluded", icon: "✕",
    text: "At least one trial criterion blocks this patient. See the red items below.",
  },
};

const GROUPS = [
  { key: "BLOCKS", title: "Blocks this patient", icon: "✕", hint: "The case clearly fails a trial rule" },
  { key: "SUPPORTS", title: "Met by this patient", icon: "✓", hint: "The case clearly satisfies a trial rule" },
  { key: "UNKNOWN", title: "Needs more information", icon: "?", hint: "The case does not say enough to decide" },
];

export default function TrialCard({ match: m }) {
  const [showSources, setShowSources] = useState(false);
  const v = VERDICT[m.verdict];
  const pct = Math.round(Math.max(0, Math.min(1, m.relevance_score)) * 100);
  const by = (k) => m.criteria.filter((c) => c.impact === k);

  const defaultOpen = (k) =>
    k === "BLOCKS" ||
    (k === "UNKNOWN" && m.verdict === "POSSIBLY_ELIGIBLE") ||
    (k === "SUPPORTS" && m.verdict === "ELIGIBLE");

  return (
    <article className={`card v-${m.verdict}`}>
      <div className={`verdict-banner vb-${m.verdict}`}>
        <span className="vicon">{v.icon}</span>
        <div>
          <strong>{v.label}</strong>
          <p>{v.text}</p>
        </div>
        <span className="rank">#{m.rank}</span>
      </div>

      <div className="card-body">
        <h3>{m.title}</h3>
        <div className="sub">
          <a href={m.url} target="_blank" rel="noreferrer">{m.nct_id} ↗ view on ClinicalTrials.gov</a>
          <span>{m.status}</span>
          {m.phases.length > 0 && <span>{m.phases.join(", ")}</span>}
        </div>

        <div className="chips">{m.conditions.map((c) => <em key={c} className="chip">{c}</em>)}</div>

        <div className="meter-row">
          <div className="meter-label">Topic match <b>{pct}%</b></div>
          <div className="meter"><div style={{ width: `${pct}%` }} /></div>
          <div className="meter-note">How close this trial is to the patient's condition. It is not an eligibility score.</div>
        </div>

        <div className="tally">
          <div className="tl tl-SUPPORTS"><b>{by("SUPPORTS").length}</b><span>met</span></div>
          <div className="tl tl-BLOCKS"><b>{by("BLOCKS").length}</b><span>blocking</span></div>
          <div className="tl tl-UNKNOWN"><b>{by("UNKNOWN").length}</b><span>unknown</span></div>
        </div>

        <div className="why-box">
          <small>Summary</small>
          <p>{m.summary}</p>
        </div>

        {GROUPS.map((g) => {
          const items = by(g.key);
          if (!items.length) return null;
          return (
            <details key={g.key} className={`group g-${g.key}`} open={defaultOpen(g.key)}>
              <summary>
                <span className={`gicon gi-${g.key}`}>{g.icon}</span>
                <span className="gtitle">{g.title} <em>({items.length})</em></span>
                <span className="ghint">{g.hint}</span>
              </summary>
              <div className="crit-list">
                {items.map((c, i) => (
                  <div key={i} className="crit">
                    <div className="crit-meta">
                      {c.criterion_type.toLowerCase()} rule · {c.source === "STRUCTURED" ? "registry field" : "trial text"}
                    </div>
                    <blockquote>
                      <small>Trial says</small>
                      {c.criterion_quote}
                    </blockquote>
                    {c.patient_evidence && (
                      <blockquote className="patient">
                        <small>Patient record says</small>
                        {c.patient_evidence}
                      </blockquote>
                    )}
                    <p className="why">{c.explanation}</p>
                  </div>
                ))}
              </div>
            </details>
          );
        })}

        <button className="link" onClick={() => setShowSources(!showSources)}>
          {showSources ? "Hide" : "Show"} retrieved passages (citations)
        </button>
        {showSources && (
          <div className="sources">
            {m.passages.map((p, i) => (
              <div key={i} className="passage"><b>{p.chunk_type}</b><p>{p.text}</p></div>
            ))}
          </div>
        )}

        <div className="foot">
          {m.sponsor && <span>Sponsor: {m.sponsor}</span>}
          {m.locations[0] && <span>{m.locations[0]}</span>}
          {m.dropped_unverified > 0 && (
            <span className="warn">{m.dropped_unverified} unverifiable AI statement(s) removed</span>
          )}
        </div>
      </div>
    </article>
  );
}