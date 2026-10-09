import { useState } from "react";
import { matchPatient } from "./api";
import ProfilePanel from "./components/ProfilePanel";
import TrialCard from "./components/TrialCard";

const SAMPLE = `62-year-old woman with newly diagnosed stage IIIB non-small cell lung cancer, adenocarcinoma, EGFR exon 19 deletion positive, PD-L1 40%. ECOG performance status 1. Past medical history: type 2 diabetes controlled on metformin, hypertension on lisinopril. No prior systemic chemotherapy or radiotherapy. Brain MRI shows no metastases. Creatinine 0.9 mg/dL, ALT within normal limits. Never smoker. No history of interstitial lung disease.`;

export default function App() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setLoading(true); setError(""); setData(null);
    try { setData(await matchPatient(text)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  return (
    <div className="app">
      <header className="hero">
        <div className="logo">+</div>
        <div>
          <h1>Clinical Trial Matcher</h1>
          <p>Evidence-grounded eligibility reasoning over recruiting ClinicalTrials.gov studies</p>
        </div>
      </header>

      <main className="layout">
        <section className="panel input">
          <div className="panel-head">
            <h2>Anonymised patient case</h2>
            <button className="link" onClick={() => setText(SAMPLE)}>Load sample</button>
          </div>
          <textarea
            value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Paste a de-identified case: demographics, diagnosis, staging, biomarkers, prior therapy, comorbidities, labs…"
          />
          <button className="primary" disabled={loading || text.trim().length < 40} onClick={submit}>
            {loading ? "Analysing trials…" : "Find matching trials"}
          </button>
          {error && <div className="error">{error}</div>}
          {data && <ProfilePanel profile={data.patient_profile} />}
        </section>

        <section className="results">
          {loading && [1, 2, 3].map((i) => <div key={i} className="skeleton" />)}
          {!loading && !data && (
            <div className="empty">
              <h3>No results yet</h3>
              <p>Results include verbatim trial criteria and patient evidence for every decision.</p>
            </div>
          )}
          {data && (
            <>
              <div className="meta">Top {data.matches.length} trials · {data.latency_seconds}s</div>
              {data.matches.map((m) => <TrialCard key={m.nct_id} match={m} />)}
              <p className="disclaimer">{data.disclaimer}</p>
            </>
          )}
        </section>
      </main>
    </div>
  );
}