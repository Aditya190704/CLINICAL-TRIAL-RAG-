
import { useEffect, useRef, useState } from "react";
import { matchPatient } from "./api";
import ProfilePanel from "./components/ProfilePanel";
import TrialCard from "./components/TrialCard";
import ChatPanel from "./components/ChatPanel";

const SAMPLE = `62-year-old woman with newly diagnosed stage IIIB non-small cell lung cancer, adenocarcinoma, EGFR exon 19 deletion positive, PD-L1 40%. ECOG performance status 1. Past medical history: type 2 diabetes controlled on metformin, hypertension on lisinopril. No prior systemic chemotherapy or radiotherapy. Brain MRI shows no metastases. Creatinine 0.9 mg/dL, ALT within normal limits. Never smoker. No history of interstitial lung disease.`;

const STEPS = [
  "Reading the patient case",
  "Searching recruiting trials",
  "Checking eligibility criteria",
  "Verifying evidence and citations",
];

const VERDICT_LABELS = {
  ELIGIBLE: "Likely eligible",
  POSSIBLY_ELIGIBLE: "Possibly eligible",
  EXCLUDED: "Excluded",
};

export default function App() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);
  const [activeTab, setActiveTab] = useState(0);
  const [chatOpen, setChatOpen] = useState(false);

  const resultsRef = useRef(null);

  useEffect(() => {
    if (!loading) return undefined;

    setStep(0);

    const timer = window.setInterval(() => {
      setStep((current) =>
        Math.min(current + 1, STEPS.length - 1)
      );
    }, 5500);

    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    if (!chatOpen) return undefined;

    const handleEscape = (event) => {
      if (event.key === "Escape") {
        setChatOpen(false);
      }
    };

    window.addEventListener("keydown", handleEscape);

    return () => {
      window.removeEventListener("keydown", handleEscape);
    };
  }, [chatOpen]);

  async function submit() {
    if (loading || text.trim().length < 40) return;

    setLoading(true);
    setError("");
    setData(null);
    setActiveTab(0);
    setChatOpen(false);

    try {
      const result = await matchPatient(text.trim());

      if (!result || !Array.isArray(result.matches)) {
        throw new Error(
          "The server response does not contain a valid matches list."
        );
      }

      setData(result);

      window.setTimeout(() => {
        resultsRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 120);
    } catch (err) {
      setError(
        err?.message ||
          "Something went wrong while matching trials."
      );
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(event) {
    if (
      (event.ctrlKey || event.metaKey) &&
      event.key === "Enter"
    ) {
      event.preventDefault();
      submit();
    }
  }

  const matches = data?.matches ?? [];
  const selectedMatch = matches[activeTab];

  return (
    <div className="app-shell">
      {/* Header */}
      <header className="app-header">
        <a
          className="header-brand"
          href="#top"
          aria-label="Clinical Trial Matcher home"
        >
          <div className="header-logo" aria-hidden="true">
            ✚
          </div>

          <div>
            <div className="header-title">
              Clinical Trial Matcher
            </div>

            <div className="header-subtitle">
              Evidence-first clinical research assistant
            </div>
          </div>
        </a>

        <div className="header-steps">
          {["Paste case", "Match trials", "Review evidence"].map(
            (label, index) => (
              <div className="step-pill" key={label}>
                <span className="step-num">{index + 1}</span>
                {label}
              </div>
            )
          )}
        </div>

        <div className="header-status">
          <span className="status-dot" />
          Research workspace
        </div>
      </header>

      <main id="top">
        {/* Hero and patient input */}
        <section className="hero-section">
          <div className="hero-eyebrow">
            <span className="hero-badge-dot" />
            CLINICAL RESEARCH WORKSPACE
          </div>

          <h1 className="hero-title">
            Find relevant trials.
            <br />
            <span>Understand the evidence.</span>
          </h1>

          <p className="hero-desc">
            Enter an anonymised patient case to retrieve relevant
            clinical trials and review each eligibility criterion
            against the available evidence.
          </p>

          <div className="input-card">
            <div className="input-card-top">
              <div>
                <div className="input-label-text">
                  <span className="label-icon">01</span>
                  Patient case
                </div>

                <p className="input-helper">
                  Include diagnosis, stage, biomarkers, previous
                  treatment, comorbidities and relevant lab results.
                </p>
              </div>

              <button
                className="load-sample-btn"
                type="button"
                onClick={() => setText(SAMPLE)}
              >
                Use sample case <span>↗</span>
              </button>
            </div>

            <textarea
              className="case-textarea"
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Paste an anonymised patient case here..."
              aria-label="Anonymised patient case"
              maxLength={12000}
              disabled={loading}
            />

            <div className="input-footer">
              <span
                className={`char-count ${
                  text.trim().length >= 40 ? "ready" : ""
                }`}
              >
                <span className="privacy-icon">⌑</span>
                {text.length.toLocaleString()} characters ·{" "}
                {text.trim().length < 40
                  ? `${40 - text.trim().length} more needed`
                  : "Ready to analyse"}{" "}
                · Ctrl/⌘ + Enter
              </span>

              <button
                className="analyze-btn"
                disabled={loading || text.trim().length < 40}
                onClick={submit}
              >
                {loading ? (
                  <>
                    <span className="button-spinner" />
                    Analysing case...
                  </>
                ) : (
                  <>
                    Find matching trials
                    <span aria-hidden="true">→</span>
                  </>
                )}
              </button>
            </div>

            {error && (
              <div className="error-banner" role="alert">
                <strong>Could not complete the request.</strong>
                <span>{error}</span>
              </div>
            )}
          </div>

          <div className="trust-row">
            <span>✓ Evidence-linked results</span>
            <span>✓ Criterion-level review</span>
            <span>✓ Source citations</span>
          </div>
        </section>

        {/* Loading state */}
        {loading && (
          <section className="loading-section" aria-live="polite">
            <div className="loading-orb">
              <span className="loading-spinner" />
            </div>

            <div className="loading-title">
              Reviewing the patient case
            </div>

            <p className="loading-desc">
              Retrieving trial evidence and checking the available
              eligibility information.
            </p>

            <ul className="loading-steps">
              {STEPS.map((label, index) => (
                <li
                  key={label}
                  className={`loading-step ${
                    index < step
                      ? "done"
                      : index === step
                      ? "active"
                      : ""
                  }`}
                >
                  <span className="step-icon">
                    {index < step ? (
                      "✓"
                    ) : index === step ? (
                      <span className="mini-spinner" />
                    ) : (
                      index + 1
                    )}
                  </span>
                  {label}
                </li>
              ))}
            </ul>

            <div className="progress-bar">
              <div className="progress-fill" />
            </div>
          </section>
        )}

        {/* Initial empty state */}
        {!loading && !data && (
          <section className="empty-section">
            <div className="empty-visual">
              <div className="empty-icon-wrap">⌕</div>
              <span className="orbit orbit-one" />
              <span className="orbit orbit-two" />
            </div>

            <div className="empty-kicker">
              YOUR RESULTS WILL APPEAR HERE
            </div>

            <h2 className="empty-title">
              Start with a patient profile
            </h2>

            <p className="empty-desc">
              Run a search to see your trial matches, eligibility
              reasoning, criteria status and source evidence.
            </p>

            <div className="legend-row">
              <span className="legend-tag met">
                <i /> Criterion supported
              </span>

              <span className="legend-tag blocks">
                <i /> Potential exclusion
              </span>

              <span className="legend-tag unknown">
                <i /> Needs more information
              </span>
            </div>
          </section>
        )}

        {/* Search results */}
        {data && !loading && (
          <section className="results-section" ref={resultsRef}>
            <div className="section-eyebrow">MATCH RESULTS</div>

            <div className="results-header">
              <div>
                <h2 className="results-heading">
                  Your trial shortlist
                </h2>

                <p className="results-subheading">
                  Review the evidence before interpreting eligibility.
                </p>
              </div>

              <div className="results-summary">
                <strong>{matches.length}</strong>
                <span>trials found</span>
              </div>
            </div>

            {data.patient_profile && (
              <ProfilePanel profile={data.patient_profile} />
            )}

            {matches.length === 0 ? (
              <div className="no-matches">
                <div className="no-matches-icon">⌕</div>
                <h3>No matching trials returned</h3>
                <p>
                  Try adding more clinical details or check the
                  backend logs for retrieval errors.
                </p>
              </div>
            ) : (
              <>
                {/* Trial selector */}
                <div
                  className="trial-tabs"
                  role="tablist"
                  aria-label="Matched trials"
                >
                  {matches.map((match, index) => (
                    <button
                      key={match.nct_id || index}
                      type="button"
                      role="tab"
                      aria-selected={index === activeTab}
                      className={`trial-tab ${
                        index === activeTab ? "active" : ""
                      }`}
                      onClick={() => setActiveTab(index)}
                    >
                      <div className="tab-topline">
                        <span className="tab-rank-badge">
                          MATCH #{match.rank ?? index + 1}
                        </span>

                        <span
                          className={`verdict-pill ${
                            match.verdict || "POSSIBLY_ELIGIBLE"
                          }`}
                        >
                          {VERDICT_LABELS[match.verdict] ||
                            "Needs review"}
                        </span>
                      </div>

                      <div className="tab-trial-title">
                        {match.title || "Untitled clinical trial"}
                      </div>

                      <div className="tab-trial-id">
                        {match.nct_id || "Trial ID unavailable"}
                        <span>↗</span>
                      </div>
                    </button>
                  ))}
                </div>

                {selectedMatch && (
                  <TrialCard
                    key={selectedMatch.nct_id || activeTab}
                    match={selectedMatch}
                    index={activeTab}
                  />
                )}

                {/* Chat launcher */}
                <div className="chat-launcher-section">
                  <div className="chat-cta-copy">
                    <span className="chat-cta-icon">✳</span>

                    <div>
                      <strong>Need to dig deeper?</strong>
                      <p>
                        Ask a follow-up about these trials and their
                        criteria.
                      </p>
                    </div>
                  </div>

                  <button
                    className="chat-launch-btn"
                    type="button"
                    onClick={() => setChatOpen(true)}
                  >
                    <span className="chat-btn-icon">✳</span>
                    Ask about these trials
                    <span className="chat-btn-arrow">↗</span>
                  </button>
                </div>
              </>
            )}

            <div className="medical-disclaimer">
              <span>ⓘ</span>
              <p>
                {data.disclaimer ||
                  "This tool supports research and does not replace clinical judgement. Eligibility must be confirmed by the study team."}
              </p>
            </div>
          </section>
        )}
      </main>

      {/* AI chat modal */}
      {chatOpen && data && matches.length > 0 && (
        <ChatPanel
          trialIds={matches
            .map((match) => match.nct_id)
            .filter(Boolean)}
          trialTitles={matches.map((match) => ({
            id: match.nct_id,
            title: match.title,
          }))}
          patientCase={text}
          onClose={() => setChatOpen(false)}
        />
      )}

      <footer className="app-footer">
        <span>Clinical Trial Matcher</span>
        <span>
          Evidence-informed research support · Not a medical decision
        </span>
      </footer>
    </div>
  );
}
