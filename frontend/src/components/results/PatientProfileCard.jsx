import React, { useState } from "react";
import Badge from "../ui/Badge";

/**
 * Extracted Patient Profile Component.
 * Displays structured facts with support for both schema standards and raw case viewing.
 */
export default function PatientProfileCard({
  profile = {},
  patientCase = "",
}) {
  const [showRawCase, setShowRawCase] = useState(false);

  if (!profile || typeof profile !== "object") return null;

  // Extract canonical or fallback fields
  const age =
    profile.age_years != null
      ? `${Math.round(profile.age_years)} years`
      : profile.age || null;

  const sex =
    profile.sex && profile.sex !== "UNKNOWN"
      ? profile.sex.charAt(0).toUpperCase() + profile.sex.slice(1).toLowerCase()
      : null;

  const conditions = Array.isArray(profile.primary_conditions)
    ? profile.primary_conditions
    : Array.isArray(profile.conditions)
    ? profile.conditions
    : profile.diagnosis
    ? [profile.diagnosis]
    : [];

  const findings = Array.isArray(profile.key_findings)
    ? profile.key_findings
    : Array.isArray(profile.biomarkers)
    ? profile.biomarkers
    : [];

  const priorTreatments = Array.isArray(profile.prior_treatments)
    ? profile.prior_treatments
    : [];

  const comorbidities = Array.isArray(profile.comorbidities)
    ? profile.comorbidities
    : [];

  const medications = Array.isArray(profile.current_medications)
    ? profile.current_medications
    : [];

  const searchQuery = profile.search_query || null;

  const hasAnyData =
    age ||
    sex ||
    conditions.length > 0 ||
    findings.length > 0 ||
    priorTreatments.length > 0 ||
    comorbidities.length > 0;

  if (!hasAnyData && !patientCase) return null;

  return (
    <div className="patient-profile-card">
      <div className="profile-header">
        <div className="profile-header-title">
          <span className="profile-header-icon">👤</span>
          <div>
            <h3 className="profile-title">Extracted Clinical Profile</h3>
            <p className="profile-subtitle">
              Structured facts extracted by Gemini from the patient narrative
            </p>
          </div>
        </div>

        {patientCase && (
          <button
            type="button"
            className="toggle-raw-case-btn"
            onClick={() => setShowRawCase(!showRawCase)}
          >
            {showRawCase ? "Hide original case" : "View original case ↗"}
          </button>
        )}
      </div>

      {hasAnyData && (
        <div className="profile-grid">
          {/* Patient Demographics */}
          {(age || sex) && (
            <div className="profile-field">
              <span className="field-label">Patient Demographics</span>
              <div className="field-tags">
                {age && <Badge variant="neutral">{age}</Badge>}
                {sex && <Badge variant="neutral">{sex}</Badge>}
              </div>
            </div>
          )}

          {/* Primary Condition(s) */}
          {conditions.length > 0 && (
            <div className="profile-field profile-field-wide">
              <span className="field-label">Primary Diagnosis</span>
              <div className="field-tags">
                {conditions.map((c, i) => (
                  <Badge key={i} variant="primary">
                    {c}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Key Findings / Biomarkers / Staging */}
          {findings.length > 0 && (
            <div className="profile-field profile-field-wide">
              <span className="field-label">Key Findings & Biomarkers</span>
              <div className="field-tags">
                {findings.map((f, i) => (
                  <Badge key={i} variant="info">
                    {f}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Prior Treatments */}
          {priorTreatments.length > 0 && (
            <div className="profile-field profile-field-wide">
              <span className="field-label">Prior Treatments</span>
              <div className="field-tags">
                {priorTreatments.map((t, i) => (
                  <Badge key={i} variant="neutral">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Comorbidities */}
          {comorbidities.length > 0 && (
            <div className="profile-field profile-field-wide">
              <span className="field-label">Comorbidities</span>
              <div className="field-tags">
                {comorbidities.map((c, i) => (
                  <Badge key={i} variant="neutral">
                    {c}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Current Medications */}
          {medications.length > 0 && (
            <div className="profile-field profile-field-wide">
              <span className="field-label">Current Medications</span>
              <div className="field-tags">
                {medications.map((m, i) => (
                  <Badge key={i} variant="neutral">
                    {m}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* AI search query */}
      {searchQuery && (
        <div className="profile-search-query">
          <span className="query-label">Condition Query:</span>
          <code className="query-code">{searchQuery}</code>
        </div>
      )}

      {/* Collapsible raw narrative case */}
      {showRawCase && patientCase && (
        <div className="raw-case-viewer">
          <div className="raw-case-header">
            <span>Original Clinical Narrative Case</span>
            <button
              type="button"
              className="raw-case-close"
              onClick={() => setShowRawCase(false)}
            >
              ✕
            </button>
          </div>
          <p className="raw-case-text">{patientCase}</p>
        </div>
      )}
    </div>
  );
}

