import React, { useState, useEffect, useRef } from "react";
import AppShell from "./components/layout/AppShell";
import Header from "./components/layout/Header";
import Footer from "./components/layout/Footer";
import SessionSidebar from "./components/session/SessionSidebar";
import ResultsOverview from "./components/results/ResultsOverview";
import PatientProfileCard from "./components/results/PatientProfileCard";
import TrialTabs from "./components/results/TrialTabs";
import TrialDetailView from "./components/results/TrialDetailView";
import ChatDrawer from "./components/chat/ChatDrawer";
import Toast from "./components/ui/Toast";
import Button from "./components/ui/Button";
import { SkeletonCard } from "./components/ui/Skeleton";

import { matchPatient, checkHealth } from "./api";
import { useSessionManager } from "./hooks/useSessionManager";
import { useToast } from "./hooks/useToast";

const SAMPLE_CASE = `62-year-old woman with newly diagnosed stage IIIB non-small cell lung cancer, adenocarcinoma, EGFR exon 19 deletion positive, PD-L1 40%. ECOG performance status 1. Past medical history: type 2 diabetes controlled on metformin, hypertension on lisinopril. No prior systemic chemotherapy or radiotherapy. Brain MRI shows no metastases. Creatinine 0.9 mg/dL, ALT within normal limits. Never smoker. No history of interstitial lung disease.`;

const MATCH_STEPS = [
  "Extracting patient demographics, condition & biomarkers",
  "Executing BigQuery semantic vector search",
  "Evaluating trial eligibility rules with Gemini",
  "Verifying verbatim quotes & computing final verdicts",
];

export default function App() {
  const {
    sessions,
    activeSessionId,
    activeSession,
    switchSession,
    createNewSession,
    updateActiveSession,
    renameSession,
    deleteSession,
    clearAllSessions,
  } = useSessionManager();

  const { toast, showToast, hideToast } = useToast();

  // Local state bound to active session
  const [patientText, setPatientText] = useState("");
  const [loading, setLoading] = useState(false);
  const [matchStep, setMatchStep] = useState(0);
  const [error, setError] = useState("");
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [healthStatus, setHealthStatus] = useState("online");
  const [trialCount, setTrialCount] = useState(484);

  const resultsRef = useRef(null);

  // Sync local text input when active session changes
  useEffect(() => {
    if (activeSession) {
      setPatientText(activeSession.patientCase || "");
      setError("");
    }
  }, [activeSession?.id]);

  // Check backend health on mount
  useEffect(() => {
    let mounted = true;
    checkHealth()
      .then((res) => {
        if (!mounted) return;
        if (res && res.status === "ok") {
          setHealthStatus("online");
          if (res.trials_indexed) setTrialCount(res.trials_indexed);
        } else {
          setHealthStatus("offline");
        }
      })
      .catch(() => {
        if (mounted) setHealthStatus("offline");
      });

    return () => {
      mounted = false;
    };
  }, []);

  // Step ticker animation during loading
  useEffect(() => {
    if (!loading) {
      setMatchStep(0);
      return undefined;
    }

    setMatchStep(0);
    const interval = setInterval(() => {
      setMatchStep((prev) => Math.min(prev + 1, MATCH_STEPS.length - 1));
    }, 4500);

    return () => clearInterval(interval);
  }, [loading]);

  // Handle case submission
  const handleSubmit = async (e) => {
    e?.preventDefault();
    const cleanCase = patientText.trim();
    if (cleanCase.length < 40 || loading) return;

    setLoading(true);
    setError("");

    try {
      const result = await matchPatient(cleanCase);

      if (!result || !Array.isArray(result.matches)) {
        throw new Error("Invalid response format received from matching service.");
      }

      // Save match result to current active session
      updateActiveSession({
        patientCase: cleanCase,
        data: result,
        activeTab: 0,
      });

      showToast(
        `Retrieved and evaluated ${result.matches.length} candidate trials`,
        "success"
      );

      // Smooth scroll to results
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 150);
    } catch (err) {
      const msg = err?.message || "Failed to match clinical trials.";
      setError(msg);
      showToast(msg, "error");
    } finally {
      setLoading(false);
    }
  };

  const handleTextChange = (e) => {
    const val = e.target.value;
    setPatientText(val);
    updateActiveSession({ patientCase: val });
  };

  const handleLoadSample = () => {
    setPatientText(SAMPLE_CASE);
    updateActiveSession({ patientCase: SAMPLE_CASE });
    showToast("Loaded sample NSCLC clinical case", "info");
  };

  const handleClearCase = () => {
    setPatientText("");
    updateActiveSession({ patientCase: "", data: null });
  };

  const handleSelectTab = (index) => {
    updateActiveSession({ activeTab: index });
  };

  const handleUpdateChatHistory = (newHistory) => {
    updateActiveSession({ chatHistory: newHistory });
  };

  const handleCopySummary = () => {
    if (!activeSession?.data?.matches) return;
    const matches = activeSession.data.matches;
    const lines = [
      `Clinical Trial Match Summary (${matches.length} candidate trials)`,
      `Session: ${activeSession.title}`,
      `Date: ${new Date().toLocaleDateString()}`,
      "",
      ...matches.map(
        (m, i) =>
          `#${i + 1} [${m.verdict}] ${m.nct_id}: ${m.title} (Match: ${Math.round(
            (m.relevance_score || 0) * 100
          )}%)`
      ),
    ];
    navigator.clipboard.writeText(lines.join("\n")).catch(() => {});
    showToast("Summary copied to clipboard", "success");
  };

  const currentData = activeSession?.data || null;
  const currentMatches = currentData?.matches || [];
  const currentActiveTab = Math.min(
    activeSession?.activeTab || 0,
    Math.max(0, currentMatches.length - 1)
  );
  const selectedMatch = currentMatches[currentActiveTab] || null;

  return (
    <AppShell
      isSidebarOpen={isSidebarOpen}
      header={
        <Header
          healthStatus={healthStatus}
          trialCount={trialCount}
          sessionCount={sessions.length}
          isSidebarOpen={isSidebarOpen}
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          onNewSession={() => {
            createNewSession();
            showToast("Started a new patient matching session", "info");
          }}
          onLoadSample={handleLoadSample}
          hasResults={currentMatches.length > 0}
          onOpenChat={() => setIsChatOpen(true)}
        />
      }
      sidebar={
        <SessionSidebar
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={(id) => {
            switchSession(id);
            showToast("Loaded session", "info");
          }}
          onNewSession={() => {
            createNewSession();
            showToast("Started a new session", "info");
          }}
          onRenameSession={(id, title) => {
            renameSession(id, title);
            showToast("Session renamed", "success");
          }}
          onDeleteSession={(id) => {
            deleteSession(id);
            showToast("Session removed", "info");
          }}
          onClearAllSessions={() => {
            clearAllSessions();
            showToast("All sessions cleared", "info");
          }}
        />
      }
      footer={<Footer />}
    >
      {/* ── Main Input Card ── */}
      <section className="input-panel-section">
        <div className="section-header-row">
          <div>
            <span className="section-eyebrow">PATIENT CASE INTAKE</span>
            <h2 className="section-heading">Clinical Narrative Analysis</h2>
            <p className="section-subtext">
              Enter an anonymized clinical note (age, sex, histology, stage, biomarkers, prior therapies, comorbidities, and laboratory values).
            </p>
          </div>

          <div className="input-quick-actions">
            <Button
              variant="outline"
              size="sm"
              onClick={handleLoadSample}
              icon="📄"
              title="Load sample stage IIIB NSCLC case"
            >
              Use Sample Case
            </Button>
            {patientText && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClearCase}
                title="Clear patient input"
              >
                Clear
              </Button>
            )}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="case-input-form">
          <div className="textarea-wrapper">
            <textarea
              className="patient-textarea"
              value={patientText}
              onChange={handleTextChange}
              placeholder="Paste anonymized patient summary: e.g. 62-year-old woman with stage IIIB non-small cell lung cancer, EGFR exon 19 deletion positive, ECOG 1, prior metformin for diabetes, normal renal function..."
              rows={5}
              disabled={loading}
              aria-label="Anonymized patient case"
            />
          </div>

          <div className="input-action-bar">
            <div className="char-indicator">
              <span
                className={`char-count-pill ${
                  patientText.trim().length >= 40 ? "char-valid" : "char-insufficient"
                }`}
              >
                {patientText.trim().length} characters
              </span>
              <span className="char-min-note">
                {patientText.trim().length < 40
                  ? `(minimum 40 characters required, ${40 - patientText.trim().length} more needed)`
                  : "✓ Ready for trial matching"}
              </span>
            </div>

            <Button
              variant="primary"
              size="lg"
              type="submit"
              disabled={loading || patientText.trim().length < 40}
              loading={loading}
              icon="🔍"
              title="Run vector retrieval and Gemini eligibility judge"
            >
              {loading ? "Matching Trials..." : "Find Matching Trials"}
            </Button>
          </div>

          {error && (
            <div className="error-banner" role="alert">
              <span className="error-icon">⚠</span>
              <span className="error-text">{error}</span>
            </div>
          )}
        </form>
      </section>

      {/* ── Stepped Loading State ── */}
      {loading && (
        <section className="loading-state-panel" aria-live="polite">
          <div className="loading-card">
            <div className="loading-header">
              <div className="loading-spinner-orbit" />
              <div>
                <h3 className="loading-title">Matching Patient Case</h3>
                <p className="loading-subtitle">
                  Retrieving candidate trials from BigQuery and evaluating criteria against documented patient facts.
                </p>
              </div>
            </div>

            <div className="steps-progress-list">
              {MATCH_STEPS.map((step, idx) => {
                const isDone = idx < matchStep;
                const isCurrent = idx === matchStep;

                return (
                  <div
                    key={idx}
                    className={`step-item ${isDone ? "step-done" : isCurrent ? "step-current" : "step-pending"}`}
                  >
                    <div className="step-circle">
                      {isDone ? "✓" : isCurrent ? <span className="step-pulse" /> : idx + 1}
                    </div>
                    <span className="step-label">{step}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Shimmer skeleton placeholders */}
          <div className="skeleton-grid">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        </section>
      )}

      {/* ── Empty State ── */}
      {!loading && !currentData && (
        <section className="empty-state-panel">
          <div className="empty-state-card">
            <div className="empty-illustration">🔬</div>
            <h3 className="empty-title">Ready to find recruiting clinical trials</h3>
            <p className="empty-description">
              Paste an anonymized case above and click <strong>Find Matching Trials</strong>. The system will retrieve the most relevant studies and audit every inclusion and exclusion criterion against your case.
            </p>

            <div className="empty-features-grid">
              <div className="feature-pill">
                <span className="feature-icon">⚡</span>
                <div>
                  <strong>BigQuery Vector Search</strong>
                  <p>Dense semantic retrieval across 1,600+ trial criteria chunks</p>
                </div>
              </div>
              <div className="feature-pill">
                <span className="feature-icon">🛡️</span>
                <div>
                  <strong>Evidence-Verified Verdicts</strong>
                  <p>Every criterion decision requires verbatim proof from source trial text</p>
                </div>
              </div>
              <div className="feature-pill">
                <span className="feature-icon">💬</span>
                <div>
                  <strong>Trial Q&A Assistant</strong>
                  <p>Ask follow-up questions grounded strictly in the matched studies</p>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* ── Results Area ── */}
      {!loading && currentData && (
        <section className="results-container-section" ref={resultsRef}>
          {/* Summary Metric Bar */}
          <ResultsOverview
            data={currentData}
            onCopySummary={handleCopySummary}
            onOpenChat={() => setIsChatOpen(true)}
          />

          {/* Extracted Patient Profile */}
          <PatientProfileCard
            profile={currentData.patient_profile}
            patientCase={patientText}
          />

          {/* Top Trial Shortlist */}
          {currentMatches.length > 0 ? (
            <div className="matches-wrapper">
              <div className="shortlist-header">
                <div>
                  <span className="section-eyebrow">TRIAL SHORTLIST</span>
                  <h3 className="shortlist-title">Candidate Clinical Trials</h3>
                  <p className="shortlist-subtitle">
                    Select a trial below to review verbatim eligibility criteria and evidence citations.
                  </p>
                </div>
              </div>

              {/* Top 3 Tab Switcher */}
              <TrialTabs
                matches={currentMatches}
                activeTab={currentActiveTab}
                onSelectTab={handleSelectTab}
              />

              {/* Selected Trial Deep-Dive */}
              {selectedMatch && (
                <TrialDetailView
                  match={selectedMatch}
                  onOpenChat={() => setIsChatOpen(true)}
                  onCopyNotice={(msg) => showToast(msg, "success")}
                />
              )}
            </div>
          ) : (
            <div className="no-matches-card">
              <h4>No relevant recruiting trials were found</h4>
              <p>
                Try adding more clinical details or alternative condition synonyms to your case narrative.
              </p>
            </div>
          )}

          {/* Regulatory & Safety Disclaimer */}
          <div className="safety-disclaimer-box">
            <span className="disclaimer-icon">ⓘ</span>
            <p className="disclaimer-text">
              {currentData.disclaimer ||
                "Clinical Trial Matcher is a research decision-support tool. It does not provide medical diagnoses or treatment recommendations. Eligibility must always be validated by qualified clinical investigators and study sponsors."}
            </p>
          </div>
        </section>
      )}

      {/* ── Slide-over Chat Drawer ── */}
      <ChatDrawer
        isOpen={isChatOpen}
        onClose={() => setIsChatOpen(false)}
        trialIds={currentMatches.map((m) => m.nct_id).filter(Boolean)}
        trialTitles={currentMatches.map((m) => ({ id: m.nct_id, title: m.title }))}
        patientCase={patientText}
        sessionId={activeSessionId}
        chatHistory={activeSession?.chatHistory || []}
        onUpdateHistory={handleUpdateChatHistory}
        onShowToast={showToast}
      />

      {/* ── Floating Toast ── */}
      <Toast toast={toast} onDismiss={hideToast} />
    </AppShell>
  );
}
