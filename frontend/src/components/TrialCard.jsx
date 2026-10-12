import { useState } from "react";

const VERDICT = {
  ELIGIBLE: { label: "Likely eligible", icon: "✓", text: "No blocking criteria found. Everything assessed is supported by the case." },
  POSSIBLY_ELIGIBLE: { label: "Possibly eligible", icon: "!", text: "No blockers, but some information is missing." },
  EXCLUDED: { label: "Excluded", icon: "✕", text: "At least one trial criterion blocks this patient." },
};

const GROUPS = [
  { key: "BLOCKS", title: "Blocks", icon: "✕" },
  { key: "SUPPORTS", title: "Met", icon: "✓" },
  { key: "UNKNOWN", title: "Needs info", icon: "?" },
];

export default function TrialCard({ match: m }) {
  const [view, setView] = useState("evidence");
  const v = VERDICT[m.verdict];
  const pct = Math.round(Math.max(0, Math.min(1, m.relevance_score)) * 100);
  const by = (k) => m.criteria.filter((c) => c.impact === k);

  return (
    <article className="detail">
      {/* ---------- Fixed top: always visible ---------- */}
      <div className="d-top">
        <h3>{m.title}</h3>
        <div className="sub">
          <a href={m.url} target="_blank" rel="noreferrer">{m.nct_id} ↗</a>
          <span>{m.status}</span>
          {m.phases.length > 0 && <span>{m.phases.join(", ")}</span>}
          {m.sponsor && <span className="sponsor">{m.sponsor}</span>}
        </div>
        <div className="chips">
          {m.conditions.slice(0, 4).map((c) => <em key={c} className="chip">{c}</em>)}
        </div>

        <div className="d-metrics">
          <div className={`vbox vb-${m.verdict}`}>
            <span className="vicon">{v.icon}</span>
            <div><strong>{v.label}</strong><p>{v.text}</p></div>
          </div>
          <div className="mbox">
            <div className="mlabel">Topic match <b>{pct}%</b></div>
            <div className="meter"><div style={{ width: `${pct}%` }} /></div>
            <small>Closeness to the condition. Not an eligibility score.</small>
          </div>
          <div className="tally">
            <div className="tl tl-SUPPORTS"><b>{by("SUPPORTS").length}</b><span>met</span></div>
            <div className="tl tl-BLOCKS"><b>{by("BLOCKS").length}</b><span>blocking</span></div>
            <div className="tl tl-UNKNOWN"><b>{by("UNKNOWN").length}</b><span>unknown</span></div>
          </div>
        </div>
      </div>

      {/* ---------- Scrolling body ---------- */}
      <div className="d-body">
        <div className="d-summary"><small>Summary</small><p>{m.summary}</p></div>

        <div className="switch">
          <button className={view === "evidence" ? "on" : ""} onClick={() => setView("evidence")}>
            Eligibility evidence
          </button>
          <button className={view === "sources" ? "on" : ""} onClick={() => setView("sources")}>
            Citations ({m.passages.length})
          </button>
          {m.dropped_unverified > 0 && (
            <span className="warn">{m.dropped_unverified} unverifiable AI statement(s) removed</span>
          )}
        </div>

        {view === "evidence" ? (
          <div className="board">
            {GROUPS.map((g) => {
              const items = by(g.key);
              return (
                <div key={g.key} className={`col col-${g.key}`}>
                  <div className="col-head">
                    <span className={`gicon gi-${g.key}`}>{g.icon}</span>
                    {g.title} <em>({items.length})</em>
                  </div>
                  <div className="col-body">
                    {items.length === 0 && <div className="none">None</div>}
                    {items.map((c, i) => (
                      <div key={i} className="crit">
                        <div className="crit-meta">
                          {c.criterion_type.toLowerCase()} · {c.source === "STRUCTURED" ? "registry field" : "trial text"}
                        </div>
                        <blockquote><small>Trial says</small>{c.criterion_quote}</blockquote>
                        {c.patient_evidence && (
                          <blockquote className="patient"><small>Patient says</small>{c.patient_evidence}</blockquote>
                        )}
                        <p className="why">{c.explanation}</p>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="sources-view">
            {m.passages.map((p, i) => (
              <div key={i} className="passage"><b>{p.chunk_type}</b><p>{p.text}</p></div>
            ))}
            {m.locations[0] && <div className="loc">Location: {m.locations[0]}</div>}
          </div>
        )}
      </div>
    </article>
  );
}