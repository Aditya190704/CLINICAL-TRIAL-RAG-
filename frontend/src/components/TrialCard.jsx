import { useState } from "react";

const LABEL = { ELIGIBLE: "Likely eligible", POSSIBLY_ELIGIBLE: "Possibly eligible", EXCLUDED: "Excluded" };
const IMPACT = { SUPPORTS: "Supports", BLOCKS: "Blocks", UNKNOWN: "Not enough info" };

export default function TrialCard({ match: m }) {
  const [open, setOpen] = useState(true);
  const order = { BLOCKS: 0, SUPPORTS: 1, UNKNOWN: 2 };
  const criteria = [...m.criteria].sort((a, b) => order[a.impact] - order[b.impact]);

  return (
    <article className={`card v-${m.verdict}`}>
      <div className="card-top">
        <div className="rank">#{m.rank}</div>
        <div className="grow">
          <h3>{m.title}</h3>
          <div className="sub">
            <a href={m.url} target="_blank" rel="noreferrer">{m.nct_id} ↗</a>
            <span>{m.status}</span>
            {m.phases.length > 0 && <span>{m.phases.join(", ")}</span>}
            <span>similarity {m.relevance_score}</span>
          </div>
        </div>
        <span className={`badge b-${m.verdict}`}>{LABEL[m.verdict]}</span>
      </div>

      <div className="chips">{m.conditions.map((c) => <em key={c} className="chip">{c}</em>)}</div>
      <p className="summary">{m.summary}</p>

      <button className="link" onClick={() => setOpen(!open)}>
        {open ? "Hide" : "Show"} criterion-level evidence ({criteria.length})
      </button>

      {open && (
        <div className="criteria">
          {criteria.map((c, i) => (
            <div key={i} className={`crit i-${c.impact}`}>
              <div className="crit-head">
                <span className={`tag t-${c.impact}`}>{IMPACT[c.impact]}</span>
                <span className="ctype">{c.criterion_type.toLowerCase()} · {c.source === "STRUCTURED" ? "registry field" : "trial text"}</span>
              </div>
              <blockquote>
                <small>Trial criterion · {m.nct_id}</small>
                {c.criterion_quote}
              </blockquote>
              {c.patient_evidence && (
                <blockquote className="patient">
                  <small>Patient record</small>
                  {c.patient_evidence}
                </blockquote>
              )}
              <p className="why">{c.explanation}</p>
            </div>
          ))}
        </div>
      )}

      <details className="sources">
        <summary>Retrieved passages (citations)</summary>
        {m.passages.map((p, i) => (
          <div key={i} className="passage"><b>{p.chunk_type}</b><p>{p.text}</p></div>
        ))}
      </details>
      <div className="foot">
        {m.sponsor && <span>Sponsor: {m.sponsor}</span>}
        {m.locations[0] && <span>{m.locations[0]}</span>}
        {m.dropped_unverified > 0 && <span>{m.dropped_unverified} unverifiable model statements removed</span>}
      </div>
    </article>
  );
}