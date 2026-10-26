/** Build and download a self-contained, print-ready evidence review report. */
import { criterionImpactLabel } from "./criterionImpact.js";

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const list = (items) => (Array.isArray(items) ? items : []);

function renderList(items, emptyText) {
  const values = list(items).filter(Boolean);
  return values.length
    ? `<ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="muted">${escapeHtml(emptyText)}</p>`;
}

function renderTrial(trial, index) {
  const criteria = list(trial.criteria);
  const criterionRows = criteria.length
    ? criteria.map((criterion) => `
      <article class="criterion">
        <div class="criterion-heading"><strong>${escapeHtml(criterion.criterion_type || "Criterion")}</strong><span class="impact impact-${escapeHtml(criterion.impact || "UNKNOWN")}">${escapeHtml(criterionImpactLabel(criterion.impact, criterion.criterion_type))}</span></div>
        <p class="label">Trial source text</p><blockquote>${escapeHtml(criterion.criterion_quote || "No verified trial quote available.")}</blockquote>
        <p class="label">Patient evidence</p><blockquote>${escapeHtml(criterion.patient_evidence || "No verified patient evidence was returned. Review the original case and trial criterion.")}</blockquote>
        ${criterion.explanation ? `<p class="explanation">${escapeHtml(criterion.explanation)}</p>` : ""}
      </article>`).join("")
    : '<p class="muted">No criterion-level evidence was retained in this result.</p>';
  const url = /^https:\/\/clinicaltrials\.gov\/study\/NCT\d{8}$/i.test(trial.url || "")
    ? trial.url
    : `https://clinicaltrials.gov/study/${encodeURIComponent(trial.nct_id || "")}`;
  const score = Number.isFinite(Number(trial.relevance_score))
    ? `${Math.round(Number(trial.relevance_score) * 100)}%`
    : "Unavailable";

  return `
    <section class="trial">
      <div class="trial-heading"><div><p class="eyebrow">CANDIDATE ${index + 1} · ${escapeHtml(trial.nct_id)}</p><h2>${escapeHtml(trial.title || "Untitled trial")}</h2></div><span class="verdict">${escapeHtml(trial.verdict || "Not assessed")}</span></div>
      <p class="muted">Topic similarity: ${escapeHtml(score)}. This is a retrieval relevance score, not an eligibility probability.</p>
      <p><a href="${escapeHtml(url)}">Open official ClinicalTrials.gov record ↗</a></p>
      <p>${escapeHtml(trial.status || "Status unavailable")}${list(trial.phases).length ? ` · ${escapeHtml(list(trial.phases).join(", "))}` : ""}</p>
      <h3>Criterion evidence</h3>${criterionRows}
    </section>`;
}

function renderRuledOut(trial) {
  const id = String(trial.nct_id || "");
  const sourceUrl = `https://clinicaltrials.gov/study/${encodeURIComponent(id)}`;
  return `<article class="criterion"><div class="criterion-heading"><strong>${escapeHtml(trial.title || "Trial")}</strong><span class="impact impact-BLOCKS">Potential blocker</span></div><p><a href="${escapeHtml(sourceUrl)}">${escapeHtml(id)} · Official study record ↗</a></p><blockquote>${escapeHtml(trial.reason || "A verified blocking criterion was recorded.")}</blockquote><p class="muted">Confirm this criterion with the clinical team and official record.</p></article>`;
}

export function buildEvidenceReportHtml({ data, sessionTitle, generatedAt = new Date() }) {
  const matches = list(data?.matches);
  const ruledOut = list(data?.ruled_out_trials);
  const profile = data?.patient_profile || {};
  const savedSummary = !data?.patient_profile && matches.length > 0;
  const searchBasis = list(profile.primary_conditions).length
    ? [...new Set(list(profile.primary_conditions).filter(Boolean))]
    : profile.search_query
      ? [profile.search_query]
      : [];
  const criteria = matches.flatMap((trial) => list(trial.criteria));
  const counts = {
    SUPPORTS: criteria.filter((item) => item.impact === "SUPPORTS").length,
    BLOCKS: criteria.filter((item) => item.impact === "BLOCKS").length,
    UNKNOWN: criteria.filter((item) => item.impact === "UNKNOWN").length,
  };
  const date = generatedAt.toLocaleString();
  const trialSections = matches.length
    ? matches.map(renderTrial).join("")
    : '<section class="trial"><h2>No candidate trials returned</h2><p class="muted">This describes the search performed. It does not establish that no suitable study exists.</p></section>';

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Clinical Trial Evidence Review</title>
<style>
  :root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:#182334;background:#f3f6fa}*{box-sizing:border-box}body{margin:0;padding:32px}.report{max-width:980px;margin:auto;background:white;border:1px solid #dce4ee;border-radius:18px;padding:40px;box-shadow:0 16px 50px #1b2e4612}.topline,.trial-heading,.criterion-heading,.metrics{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.eyebrow,.label{font-size:11px;font-weight:750;letter-spacing:.11em;text-transform:uppercase;color:#64748b}.eyebrow{color:#2466c2}h1{font-size:32px;margin:8px 0}h2{font-size:20px;margin:5px 0}h3{font-size:15px;margin:24px 0 10px}.muted{color:#64748b;line-height:1.55}.meta{font-size:13px;color:#64748b}.metrics{justify-content:flex-start;margin:24px 0}.metric{min-width:130px;padding:14px 18px;border:1px solid #e2e8f0;border-radius:12px}.metric strong{display:block;font-size:24px}.basis,.trial{border-top:1px solid #e2e8f0;padding-top:22px;margin-top:25px}.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{padding:7px 11px;background:#eef5ff;border-radius:99px;color:#27538d;font-size:13px}.trial{break-inside:avoid}.verdict{white-space:nowrap;padding:7px 11px;background:#eff6ff;border-radius:99px;font-size:12px;font-weight:700}.criterion{margin:12px 0;padding:16px;border:1px solid #e2e8f0;border-radius:12px;break-inside:avoid}.impact{padding:5px 9px;border-radius:99px;font-size:11px;font-weight:700}.impact-SUPPORTS{background:#e8f7ef;color:#137345}.impact-BLOCKS{background:#fff0ee;color:#a8352b}.impact-UNKNOWN{background:#fff7e4;color:#8a5a00}.label{margin:14px 0 5px}blockquote{margin:0;padding:10px 13px;border-left:3px solid #4f83d1;background:#f7f9fc;line-height:1.55}.explanation{font-size:13px;color:#536275}.notice{padding:14px 16px;background:#fff8e8;border:1px solid #f2dfae;border-radius:10px;line-height:1.55}a{color:#1b61ba}.print{position:fixed;right:24px;top:20px;border:0;border-radius:9px;background:#205fba;color:white;padding:11px 15px;font-weight:700;cursor:pointer}@media(max-width:640px){body{padding:10px}.report{padding:22px}.topline,.trial-heading{flex-direction:column}.metrics{flex-wrap:wrap}}@media print{body{background:white;padding:0}.report{border:0;box-shadow:none;padding:0;max-width:none}.print{display:none}a{color:inherit;text-decoration:none}.trial,.criterion{break-inside:avoid}}
</style></head><body><button class="print" onclick="window.print()">Print / Save as PDF</button><main class="report">
<header class="topline"><div><p class="eyebrow">Evidence traceability report</p><h1>Clinical Trial Review</h1><p class="meta">${escapeHtml(sessionTitle || "Matching session")} · Generated ${escapeHtml(date)}</p></div><p class="meta">Generated locally from the current review result</p></header>
<p class="notice">Preliminary research decision support only. Similarity is used to retrieve trial records and is not a probability of eligibility. A qualified clinical team must verify the official record and all criteria.</p>
${savedSummary ? '<p class="notice">This saved summary omits the patient profile and patient evidence excerpts. It contains retained assessment statuses and trial text only. Rerun matching to create a report with the verified case evidence alongside each criterion.</p>' : ''}
<section class="basis"><h2>Search basis</h2><p class="muted">Validated primary conditions ground the initial search. A limited refinement may use other supported facts:</p><div class="chips">${searchBasis.length ? searchBasis.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") : `<span class="muted">Search basis unavailable in this saved result</span>`}</div><p class="muted">Missing key facts</p>${renderList(data?.missing_key_facts, "No missing facts were reported.")}<p class="muted">Conflicts to review</p>${renderList(data?.conflicting_facts, "No conflicts were reported.")}</section>
<section><h2>Evidence overview</h2><div class="metrics"><div class="metric"><strong>${matches.length}</strong><span>candidate trials</span></div><div class="metric"><strong>${counts.SUPPORTS}</strong><span>supported checks</span></div><div class="metric"><strong>${counts.BLOCKS}</strong><span>potential blockers</span></div><div class="metric"><strong>${counts.UNKNOWN}</strong><span>unassessed checks</span></div></div></section>
${trialSections}
${ruledOut.length ? `<section class="trial"><h2>Verified potential blockers</h2><p class="muted">Separate from the candidate shortlist. Each item has a blocking reason; confirm it against the official trial record.</p>${ruledOut.map(renderRuledOut).join("")}</section>` : ""}
<footer class="basis"><p class="muted">${escapeHtml(data?.disclaimer || "Clinical research decision support. Confirm all information with the official study record and qualified investigators.")}</p></footer>
</main></body></html>`;
}

export function downloadEvidenceReport(options) {
  const html = buildEvidenceReportHtml(options);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `clinical-trial-review-${new Date().toISOString().slice(0, 10)}.html`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
