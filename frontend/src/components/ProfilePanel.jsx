
import React from "react";

function ProfileItem({ label, value, wide = false }) {
  if (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  ) {
    return null;
  }

  const displayValue = Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);

  return (
    <div className={`profile-item${wide ? " profile-item-wide" : ""}`}>
      <div className="profile-item-label">{label}</div>
      <div className="profile-item-value">{displayValue}</div>
    </div>
  );
}

export default function ProfilePanel({ profile = {}, patientCase = "" }) {
  const data = profile && typeof profile === "object" ? profile : {};

  const fields = [
    { key: "age", label: "Age" },
    { key: "sex", label: "Sex" },
    { key: "diagnosis", label: "Diagnosis", wide: true },
    { key: "cancer_type", label: "Cancer type", wide: true },
    { key: "stage", label: "Disease stage" },
    { key: "biomarkers", label: "Biomarkers", wide: true },
    { key: "ecog_status", label: "ECOG performance status" },
    { key: "prior_treatments", label: "Prior treatments", wide: true },
    { key: "comorbidities", label: "Comorbidities", wide: true },
    { key: "organ_function", label: "Organ function", wide: true },
    { key: "other_details", label: "Other details", wide: true },
  ];

  const hasProfileData = fields.some(({ key }) => {
    const value = data[key];

    return (
      value !== undefined &&
      value !== null &&
      value !== "" &&
      (!Array.isArray(value) || value.length > 0)
    );
  });

  return (
    <section className="profile-panel">
      <div className="section-heading">
        <div>
          <div className="eyebrow">PATIENT OVERVIEW</div>
          <h2 className="section-title">Patient profile</h2>
          <p className="section-description">
            Clinical details used to assess potential trial eligibility.
          </p>
        </div>

        <div className="profile-icon" aria-hidden="true">
          ♙
        </div>
      </div>

      {hasProfileData ? (
        <div className="profile-grid">
          {fields.map(({ key, label, wide }) => (
            <ProfileItem
              key={key}
              label={label}
              value={data[key]}
              wide={wide}
            />
          ))}
        </div>
      ) : (
        <div className="profile-empty">
          <div className="profile-empty-icon">◎</div>
          <h3>Patient details will appear here</h3>
          <p>
            Submit a patient case to populate the extracted clinical
            profile.
          </p>
        </div>
      )}

      {patientCase && (
        <details className="patient-case-details">
          <summary>View original patient case</summary>
          <p className="patient-case-text">{patientCase}</p>
        </details>
      )}

      <div className="profile-note">
        <span className="profile-note-icon">ⓘ</span>
        <p>
          Extracted details may be incomplete. Confirm important
          clinical facts before making eligibility decisions.
        </p>
      </div>
    </section>
  );
}
