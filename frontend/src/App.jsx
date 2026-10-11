import { useEffect, useState } from "react";
import { matchPatient } from "./api";
import { BG_IMAGE_URL } from "./config";
import ProfilePanel from "./components/ProfilePanel";
import TrialCard from "./components/TrialCard";

const SAMPLE = `62-year-old woman with newly diagnosed stage IIIB non-small cell lung cancer, adenocarcinoma, EGFR exon 19 deletion positive, PD-L1 40%. ECOG performance status 1. Past medical history: type 2 diabetes controlled on metformin, hypertension on lisinopril. No prior systemic chemotherapy or radiotherapy. Brain MRI shows no metastases. Creatinine 0.9 mg/dL, ALT within normal limits. Never smoker. No history of interstitial lung disease.`;

const STEPS = [
  "Reading the patient case",
  "Searching recruiting trials",
  "Checking eligibility criteria",
  "Verifying every quote against its source",
];

export default function App() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const id = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 6000);
    return () => clearInterval(id);
  }, [loading]);

  async function submit() {
    setLoading(true); setError(""); setData(null);
    try { setData(await matchPatient(text)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  const count = (v) => (data ? data.matches.filter((m) => m.verdict === v).length : 0);

  return (
    <div className="app" style={{ "--bg-image": `url("${BG_IMAGE_URL}")` }}>
      <header className="hero">
        <div className="hero-badge">Clinical decision support</div>
        <h1>Clinical Trial Matcher</h1>
        <p>Paste an anonymised patient case. Get the 3 best open trials, with proof for every decision.</p>
        <div className="how">
          <span><b>1</b> Paste case</span>
          <i>→</i>
          <span><b>2</b> AI finds and checks trials</span>
          <i>→</i>
          <span><b>3</b> Verified quotes as evidence</span>
        </div>
      </header>

      <main className="layout">
        <section className="glass input">
          <div className="panel-head">
            <h2>Patient case</h2>
            <button className="link" onClick={() => setText(SAMPLE)}>Load sample</button>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Anonymised case only: age, sex, diagnosis, stage, biomarkers, prior treatment, comorbidities, labs..."
          />
          <div className="counter">{text.length} characters (minimum 40)</div>
          <button className="primary" disabled={loading || text.trim().length < 40} onClick={submit}>
            {loading ? "Analysing..." : "Find matching trials"}
          </button>
          {error && <div className="error">{error}</div>}
          {data && <ProfilePanel profile={data.patient_profile} />}
        </section>

        <section className="results">
          {loading && (
            <div className="glass-dark progress">
              <h3>Working on it</h3>
              <ul>
                {STEPS.map((s, i) => (
                  <li key={s} className={i < step ? "done" : i === step ? "active" : ""}>
                    <span className="dot">{i < step ? "✓" : i + 1}</span>{s}
                  </li>
                ))}
              </ul>
              <div className="bar"><div /></div>
            </div>
          )}

          {!loading && !data && (
            <div className="glass-dark empty">
              <div className="empty-icon">🧬</div>
              <h3>Your matches will appear here</h3>
              <p>Every decision shows the exact trial rule and the exact patient evidence, so you can verify it in seconds.</p>
              <div className="legend">
                <span className="tag t-SUPPORTS">✓ Met</span>
                <span className="tag t-BLOCKS">✕ Blocks</span>
                <span className="tag t-UNKNOWN">? Needs info</span>
              </div>
            </div>
          )}

          {data && (
            <>
              <div className="summary-bar glass-dark">
                <div><b>{data.matches.length}</b><span>trials shown</span></div>
                <div className="s-green"><b>{count("ELIGIBLE")}</b><span>likely eligible</span></div>
                <div className="s-amber"><b>{count("POSSIBLY_ELIGIBLE")}</b><span>possibly eligible</span></div>
                <div className="s-red"><b>{count("EXCLUDED")}</b><span>excluded</span></div>
                <div><b>{data.latency_seconds}s</b><span>time taken</span></div>
              </div>
              {data.matches.map((m) => <TrialCard key={m.nct_id} match={m} />)}
              <p className="disclaimer">{data.disclaimer}</p>
            </>
          )}
        </section>
      </main>
    </div>
  );
}