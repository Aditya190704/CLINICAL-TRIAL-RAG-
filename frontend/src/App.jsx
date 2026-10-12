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
  "Verifying every quote",
];

const VLABEL = { ELIGIBLE: "Likely eligible", POSSIBLY_ELIGIBLE: "Possibly eligible", EXCLUDED: "Excluded" };

export default function App() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const id = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 6000);
    return () => clearInterval(id);
  }, [loading]);

  async function submit() {
    setLoading(true); setError(""); setData(null); setActive(0);
    try { setData(await matchPatient(text)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  return (
    <div className="app" style={{ "--bg-image": `url("${BG_IMAGE_URL}")` }}>
      <header className="top">
        <div className="brand">
          <div className="logo">+</div>
          <div>
            <h1>Clinical Trial Matcher</h1>
            <p>Find open trials for a patient, with proof for every decision</p>
          </div>
        </div>
        <div className="steps-pills">
          <span><b>1</b> Paste case</span>
          <span><b>2</b> AI checks trials</span>
          <span><b>3</b> Verified evidence</span>
        </div>
      </header>

      <main className="layout">
        {/* ---------------- Left: input ---------------- */}
        <section className="panel">
          <div className="panel-head">
            <h2>Patient case</h2>
            <button className="link" onClick={() => setText(SAMPLE)}>Load sample</button>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Anonymised case only: age, sex, diagnosis, stage, biomarkers, prior treatment, comorbidities, labs..."
          />
          <div className="counter">{text.length} characters · minimum 40</div>
          <button className="primary" disabled={loading || text.trim().length < 40} onClick={submit}>
            {loading ? "Analysing..." : "Find matching trials"}
          </button>
          {error && <div className="error">{error}</div>}
          {data && <ProfilePanel profile={data.patient_profile} />}
        </section>

        {/* ---------------- Right: results ---------------- */}
        <section className="stage">
          {loading && (
            <div className="center">
              <h3>Working on it</h3>
              <ul className="progress">
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
            <div className="center">
              <div className="empty-icon">🧬</div>
              <h3>Your matches will appear here</h3>
              <p>Paste an anonymised case on the left. Each decision will show the exact trial rule and the exact patient evidence.</p>
              <div className="legend">
                <span className="tag t-SUPPORTS">✓ Met</span>
                <span className="tag t-BLOCKS">✕ Blocks</span>
                <span className="tag t-UNKNOWN">? Needs info</span>
              </div>
            </div>
          )}

          {data && (
            <>
              <div className="tabs">
                {data.matches.map((m, i) => (
                  <button key={m.nct_id} className={`tab vt-${m.verdict} ${i === active ? "on" : ""}`} onClick={() => setActive(i)}>
                    <div className="tab-top">
                      <span className="tab-rank">#{m.rank}</span>
                      <span className={`pill pill-${m.verdict}`}>{VLABEL[m.verdict]}</span>
                    </div>
                    <div className="tab-title">{m.title}</div>
                  </button>
                ))}
              </div>
              <TrialCard key={data.matches[active].nct_id} match={data.matches[active]} />
              <div className="disclaimer">{data.disclaimer} · {data.latency_seconds}s</div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}