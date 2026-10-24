import React, { useState, useEffect, useRef } from "react";
import Button from "../ui/Button";
import { askTrialQuestion, clearRemoteChat } from "../../api";
import { deduplicateCitations } from "../../utils/deduplication";
import Icon from "../ui/Icon";

const SUGGESTED_QUESTIONS = [
  "Why might this patient be excluded from these trials?",
  "Compare the age and biomarker criteria across all 3 trials",
  "Which trial has the most lenient inclusion criteria?",
  "What information is missing from the case to confirm eligibility?",
];

/**
 * Format markdown-like text (headings, bold, lists) cleanly without raw syntax.
 */
function FormattedMessage({ text }) {
  if (!text) return null;

  const lines = text.split("\n");
  const elements = [];
  let currentList = [];

  const flushList = () => {
    if (currentList.length > 0) {
      elements.push(
        <ul className="chat-bullet-list" key={`list-${elements.length}`}>
          {currentList.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      currentList = [];
    }
  };

  const renderInline = (str) => {
    const parts = str.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    if (!line) {
      flushList();
      continue;
    }

    if (line.startsWith("### ") || line.startsWith("## ")) {
      flushList();
      const heading = line.replace(/^#{2,3}\s+/, "");
      elements.push(
        <h4 className="chat-msg-heading" key={`h-${i}`}>
          {renderInline(heading)}
        </h4>
      );
      continue;
    }

    if (line.startsWith("* ") || line.startsWith("- ")) {
      currentList.push(line.slice(2));
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      currentList.push(line.replace(/^\d+\.\s+/, ""));
      continue;
    }

    flushList();
    elements.push(
      <p className="chat-msg-p" key={`p-${i}`}>
        {renderInline(line)}
      </p>
    );
  }

  flushList();
  return <div className="chat-formatted-body">{elements}</div>;
}

/**
 * Slide-over Chat Drawer for evidence-grounded trial Q&A.
 */
export default function ChatDrawer({
  isOpen,
  onClose,
  trialIds = [],
  trialTitles = [],
  patientCase = "",
  sessionId = "",
  chatHistory = [],
  onUpdateHistory,
  onShowToast,
}) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copiedIndex, setCopiedIndex] = useState(null);

  const historyEndRef = useRef(null);
  const inputRef = useRef(null);

  // Focus input and scroll to bottom on open or new messages
  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
      historyEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [isOpen, chatHistory, loading]);

  // Handle Escape key
  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const handleSend = async (questionText) => {
    const q = (questionText || question).trim();
    if (!q || loading) return;

    setLoading(true);
    setError("");

    try {
      const messageId = globalThis.crypto?.randomUUID?.()
        || `turn_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
      const data = await askTrialQuestion({
        question: q,
        trialIds,
        patientCase,
        sessionId,
        messageId,
      });

      const newTurn = {
        question: q,
        answer: data.answer || "No response was returned.",
        citations: Array.isArray(data.citations)
          ? deduplicateCitations(data.citations)
          : [],
        timestamp: Date.now(),
      };

      const updated = [...chatHistory, newTurn];
      onUpdateHistory(updated);
      setQuestion("");
    } catch (err) {
      setError(err?.message || "Failed to retrieve an answer.");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCopyAnswer = (answerText, index) => {
    navigator.clipboard.writeText(answerText).catch(() => {});
    setCopiedIndex(index);
    if (onShowToast) onShowToast("Answer copied to clipboard", "success");
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const handleClearHistory = async () => {
    if (chatHistory.length > 0) {
      try {
        await clearRemoteChat(sessionId);
        onUpdateHistory([]);
        if (onShowToast) onShowToast("Chat conversation cleared", "info");
      } catch (clearError) {
        setError(clearError?.message || "Could not clear saved chat history.");
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div className="chat-drawer-overlay" role="dialog" aria-modal="true" aria-labelledby="chat-drawer-title">
      <div className="chat-drawer-backdrop" onClick={onClose} aria-hidden="true" />

      <aside className="chat-drawer-panel">
        {/* ── Header ── */}
        <div className="chat-drawer-header">
          <div className="chat-header-title-group">
            <div className="chat-avatar-icon"><Icon name="chat" size={18} /></div>
            <div>
              <h3 id="chat-drawer-title" className="chat-drawer-title">
                Trial Research Assistant
              </h3>
              <p className="chat-drawer-subtitle">
                Grounded strictly in the {trialIds.length} candidate trial{trialIds.length > 1 ? "s" : ""}
              </p>
            </div>
          </div>

          <div className="chat-header-actions">
            {chatHistory.length > 0 && (
              <button
                type="button"
                className="chat-clear-btn"
                onClick={handleClearHistory}
                title="Clear chat history"
              >
                Clear
              </button>
            )}
            <button
              type="button"
              className="chat-close-btn"
              onClick={onClose}
              aria-label="Close assistant"
            >
              ✕
            </button>
          </div>
        </div>

        {/* ── Context trial pills ── */}
        <div className="chat-context-strip">
          <span className="context-label">TRIAL CONTEXT:</span>
          <div className="context-pills">
            {trialTitles.length > 0 ? (
              trialTitles.map((t) => (
                <span key={t.id} className="context-pill" title={t.title}>
                  {t.id}
                </span>
              ))
            ) : trialIds.length > 0 ? (
              trialIds.map((id) => (
                <span key={id} className="context-pill">
                  {id}
                </span>
              ))
            ) : (
              <span className="context-pill text-muted">No trials selected</span>
            )}
          </div>
        </div>

        {/* ── Conversation History ── */}
        <div className="chat-history-container" aria-live="polite">
          {chatHistory.length === 0 ? (
            <div className="chat-welcome-state">
              <div className="welcome-icon"><Icon name="sparkle" size={20} /></div>
              <h4 className="welcome-title">Ask follow-up questions</h4>
              <p className="welcome-desc">
                Ask specific questions regarding inclusion, exclusion criteria, disease stage, previous therapies, or how the candidate trials compare.
              </p>

              <div className="suggestions-label">SUGGESTED QUESTIONS:</div>
              <div className="suggestions-list">
                {SUGGESTED_QUESTIONS.map((sug, i) => (
                  <button
                    key={i}
                    type="button"
                    className="suggestion-pill"
                    onClick={() => handleSend(sug)}
                    disabled={loading}
                  >
                    <span>{sug}</span>
                    <span className="suggestion-arrow">↗</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            chatHistory.map((turn, index) => (
              <div key={index} className="chat-turn">
                {/* User question bubble */}
                <div className="chat-question-row">
                  <div className="user-bubble">
                    <p className="user-text">{turn.question}</p>
                  </div>
                </div>

                {/* Assistant response card */}
                <div className="chat-answer-row">
                  <div className="assistant-card">
                    <div className="assistant-card-header">
                      <div className="assistant-label">
                        <span className="assistant-icon"><Icon name="sparkle" size={14} /></span>
                        <span>Clinical AI Response</span>
                      </div>
                      <button
                        type="button"
                        className="copy-answer-btn"
                        onClick={() => handleCopyAnswer(turn.answer, index)}
                        title="Copy answer"
                      >
                        {copiedIndex === index ? "✓ Copied" : "📋 Copy"}
                      </button>
                    </div>

                    <div className="assistant-card-body">
                      <FormattedMessage text={turn.answer} />
                    </div>

                    {turn.citations && turn.citations.length > 0 && (
                      <div className="assistant-citations">
                        <span className="citations-heading">EVIDENCE SOURCES:</span>
                        <div className="citations-list">
                          {turn.citations.map((c, ci) => (
                            <a
                              key={ci}
                              href={c.url || `https://clinicaltrials.gov/study/${c.nct_id}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="citation-badge"
                              title={c.excerpt || c.section || "Clinical study record"}
                            >
                              <span>{c.nct_id}</span>
                              {c.section && <span className="citation-section">• {c.section}</span>}
                              <span className="citation-link-icon">↗</span>
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}

          {loading && (
            <div className="chat-loading-row">
              <div className="chat-loading-bubble">
                <span className="chat-spinner-dot" />
                <span className="chat-spinner-dot" />
                <span className="chat-spinner-dot" />
                <span className="chat-loading-text">
                  Searching trial evidence & generating grounded answer...
                </span>
              </div>
            </div>
          )}

          <div ref={historyEndRef} />
        </div>

        {/* ── Input bar ── */}
        <div className="chat-input-bar">
          {error && (
            <div className="chat-error-banner" role="alert">
              <span>⚠ {error}</span>
            </div>
          )}

          <div className="chat-form-row">
            <textarea
              ref={inputRef}
              className="chat-input-field"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about age limits, biomarker criteria, allowed therapies... (Ctrl+Enter to send)"
              rows={2}
              disabled={loading}
              aria-label="Question about trials"
            />

            <Button
              variant="primary"
              size="md"
              onClick={() => handleSend()}
              disabled={loading || !question.trim()}
              loading={loading}
              title="Send question"
              className="chat-send-button"
            >
              Send
            </Button>
          </div>

          <div className="chat-input-hints">
            <span>Press Ctrl/⌘ + Enter to send</span>
            <span>•</span>
            <span>Answers use only verified trial criteria</span>
          </div>
        </div>
      </aside>
    </div>
  );
}

