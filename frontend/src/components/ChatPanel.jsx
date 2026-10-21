
import React, { useEffect, useRef, useState } from "react";

const API_BASE = "";

const SUGGESTIONS = [
  "Why might this patient be excluded?",
  "Compare the inclusion criteria",
  "What information is still missing?",
  "Summarise the strongest evidence",
];

function formatAnswer(text) {
  if (!text) return null;

  // Split into lines to parse paragraphs, bullet points, headers, bold text
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
    // Basic bold **text** parsing
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

    // Markdown Headers (### or ##)
    if (line.startsWith("### ") || line.startsWith("## ")) {
      flushList();
      const headingText = line.replace(/^#{2,3}\s+/, "");
      elements.push(
        <h4 className="chat-answer-heading" key={`h-${i}`}>
          {renderInline(headingText)}
        </h4>
      );
      continue;
    }

    // Bullet points (* or -)
    if (line.startsWith("* ") || line.startsWith("- ")) {
      currentList.push(line.slice(2));
      continue;
    }

    // Numbered list (1. or 2.)
    if (/^\d+\.\s+/.test(line)) {
      currentList.push(line.replace(/^\d+\.\s+/, ""));
      continue;
    }

    // Regular paragraph
    flushList();
    elements.push(
      <p className="chat-answer-p" key={`p-${i}`}>
        {renderInline(line)}
      </p>
    );
  }

  flushList();
  return elements;
}

export default function ChatPanel({
  trialIds = [],
  trialTitles = [],
  patientCase = "",
  sessionId = "",
  onClose = () => {},
}) {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const historyRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    historyRef.current?.scrollTo({
      top: historyRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [history, loading]);

  const handleSubmit = async (e, suggestedQuestion) => {
    e?.preventDefault();

    const q = (suggestedQuestion ?? question).trim();

    if (!q || loading) return;

    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_BASE}/api/trials/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: q,
          trial_ids: trialIds,
          patient_case: patientCase || null,
          session_id: sessionId || null,
        }),
      });

      const raw = await response.text();

      let data;

      try {
        data = JSON.parse(raw);
      } catch {
        throw new Error(
          `Server returned a non-JSON response: ${raw.slice(0, 180)}`
        );
      }

      if (!response.ok) {
        const detail = data?.detail || raw;

        throw new Error(
          `Request failed (${response.status}): ${
            typeof detail === "string"
              ? detail
              : JSON.stringify(detail)
          }`
        );
      }

      setHistory((previous) => [
        ...previous,
        {
          question: q,
          answer: data.answer || "No answer was returned.",
          citations: Array.isArray(data.citations)
            ? data.citations
            : [],
        },
      ]);

      setQuestion("");
    } catch (err) {
      setError(err?.message || "Unable to send your question.");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      handleSubmit(e);
    }

    if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <div
      className="chat-overlay"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="chat-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-title"
      >
        <header className="chat-modal-header">
          <div className="chat-modal-title">
            <div className="chat-modal-icon">✳</div>

            <div>
              <div id="chat-title" className="chat-modal-name">
                Trial research assistant
              </div>

              <div className="chat-modal-desc">
                <span className="status-dot" />
                Grounded in your selected trial shortlist
              </div>
            </div>
          </div>

          <button
            className="chat-close-btn"
            type="button"
            onClick={onClose}
            aria-label="Close chat"
          >
            ×
          </button>
        </header>

        <div className="chat-trial-pills">
          <span className="chat-context-label">CONTEXT</span>

          {trialTitles
            .filter((trial) => trial?.id)
            .map((trial) => (
              <span
                className="chat-trial-pill"
                key={trial.id}
                title={trial.title}
              >
                {trial.id}
              </span>
            ))}

          {trialIds.length === 0 && (
            <span className="chat-trial-pill">
              No trial IDs supplied
            </span>
          )}
        </div>

        <div
          className="chat-history"
          ref={historyRef}
          aria-live="polite"
        >
          {history.length === 0 ? (
            <div className="chat-empty-state">
              <div className="chat-empty-icon">✳</div>

              <h3>What would you like to understand?</h3>

              <p className="chat-empty-text">
                Ask about eligibility, exclusions, evidence, or how
                the selected trials compare. Verify important
                conclusions against the cited source.
              </p>

              <div className="chat-suggestions">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    type="button"
                    className="suggestion-chip"
                    key={suggestion}
                    onClick={() =>
                      handleSubmit(null, suggestion)
                    }
                    disabled={loading}
                  >
                    {suggestion}
                    <span>↗</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            history.map((item, index) => (
              <article
                className="chat-turn"
                key={`${index}-${item.question}`}
              >
                <div className="chat-q-wrap">
                  <div className="chat-q-bubble">
                    {item.question}
                  </div>
                </div>

                <div className="chat-a-wrap">
                  <div className="chat-avatar">✳</div>

                  <div className="chat-a-content">
                    <div className="chat-a-bubble">
                      {formatAnswer(item.answer)}
                    </div>

                    {item.citations.length > 0 && (
                      <div className="chat-citations-row">
                        <span className="citation-label-txt">
                          SOURCES
                        </span>

                        {item.citations.map((citation, citationIndex) =>
                          citation.url ? (
                            <a
                              key={`${
                                citation.nct_id || "source"
                              }-${citationIndex}`}
                              href={citation.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="citation-tag"
                              title={
                                citation.excerpt ||
                                citation.section ||
                                "Open source"
                              }
                            >
                              {citation.nct_id || "Trial source"}
                              {citation.section
                                ? ` · ${citation.section}`
                                : ""}{" "}
                              ↗
                            </a>
                          ) : (
                            <span
                              key={citationIndex}
                              className="citation-tag"
                            >
                              {citation.nct_id ||
                                citation.section ||
                                "Source"}
                            </span>
                          )
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </article>
            ))
          )}

          {loading && (
            <div className="chat-a-wrap">
              <div className="chat-avatar">✳</div>

              <div className="typing-bubble">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span>Reviewing evidence…</span>
              </div>
            </div>
          )}
        </div>

        <div className="chat-input-area">
          {error && (
            <div className="chat-error" role="alert">
              {error}
            </div>
          )}

          <form
            className="chat-form"
            onSubmit={handleSubmit}
          >
            <textarea
              ref={inputRef}
              className="chat-textarea"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about eligibility or trial evidence…"
              rows={2}
              disabled={loading}
              aria-label="Ask a question about the selected trials"
            />

            <button
              className="chat-send-btn"
              type="submit"
              disabled={loading || !question.trim()}
              aria-label="Send question"
            >
              {loading ? (
                <span className="button-spinner" />
              ) : (
                "↑"
              )}
            </button>
          </form>

          <div className="chat-hint">
            Ctrl/⌘ + Enter to send · Responses can be incomplete;
            check the cited trial source.
          </div>
        </div>
      </section>
    </div>
  );
}
