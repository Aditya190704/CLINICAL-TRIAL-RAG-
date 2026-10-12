const Row = ({ label, items }) =>
  items && items.length ? (
    <div className="prow">
      <span>{label}</span>
      <div>{items.map((x, i) => <em key={i} className="chip">{x}</em>)}</div>
    </div>
  ) : null;

export default function ProfilePanel({ profile }) {
  return (
    <div className="profile">
      <h3>What the AI extracted</h3>
      <div className="prow">
        <span>Patient</span>
        <div>
          <em className="chip">{profile.age_years != null ? `${profile.age_years} yrs` : "age unknown"}</em>
          <em className="chip">{profile.sex}</em>
        </div>
      </div>
      <Row label="Conditions" items={profile.primary_conditions} />
      <Row label="Comorbidities" items={profile.comorbidities} />
      <Row label="Medications" items={profile.current_medications} />
      <Row label="Prior treatment" items={profile.prior_treatments} />
      <Row label="Key findings" items={profile.key_findings} />
    </div>
  );
}