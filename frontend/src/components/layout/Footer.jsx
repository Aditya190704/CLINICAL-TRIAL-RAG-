import React from "react";

/**
 * Standard Clinical Trial Matcher Footer with compliance and research disclosures.
 */
export default function Footer() {
  return (
    <footer className="app-footer">
      <div className="footer-content">
        <div className="footer-left">
          <span className="footer-brand-name">Clinical Trial Matcher</span>
          <span className="footer-separator">•</span>
          <span className="footer-tagline">
            Decision-support research platform powered by Google Gemini & BigQuery Vector Search
          </span>
        </div>

        <div className="footer-right">
          <span className="footer-disclaimer">
            Research use only • Does not substitute professional medical judgment
          </span>
          <span className="footer-separator">•</span>
          <a
            href="https://clinicaltrials.gov"
            target="_blank"
            rel="noopener noreferrer"
            className="footer-link"
          >
            ClinicalTrials.gov ↗
          </a>
        </div>
      </div>
    </footer>
  );
}

