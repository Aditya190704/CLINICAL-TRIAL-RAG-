import React from "react";
import "./TrialCard.css";



function formatValue(value) {

  if (value === undefined || value === null || value === "") {

    return null;

  }



  if (Array.isArray(value)) {

    return value

      .map((item) => {

        if (item == null) return "";

        if (typeof item === "object") {

          return (

            item.text ||

            item.criterion_quote ||

            item.criterion ||

            item.description ||

            JSON.stringify(item)

          );

        }

        return String(item);

      })

      .filter(Boolean)

      .join(", ");

  }



  if (typeof value === "object") {

    return JSON.stringify(value);

  }



  return String(value);

}



function formatScore(score) {

  if (score === undefined || score === null || score === "") {

    return null;

  }



  const number = Number(score);


  return `${Math.round(number <= 1 ? number * 100 : number)}%`;

}



function getVerdictClass(verdict = "") {

  const value = String(verdict).toUpperCase();



  if (value === "ELIGIBLE" || value === "LIKELY ELIGIBLE") {

    return "verdict-positive";

  }



  if (

    value.includes("EXCLUDED") ||

    value.includes("INELIGIBLE") ||

    value === "NOT ELIGIBLE"

  ) {

    return "verdict-negative";

  }



  if (

    value.includes("POSSIBLY") ||

    value.includes("UNKNOWN") ||

    value.includes("REVIEW")

  ) {

    return "verdict-caution";

  }



  return "verdict-neutral";

}



function getImpactClass(impact = "") {

  switch (String(impact).toUpperCase()) {

    case "SUPPORTS":

      return "impact-supports";

    case "BLOCKS":

      return "impact-blocks";

    default:

      return "impact-unknown";

  }

}



function getOfficialUrl(trial) {
  const id = String(trial?.nct_id || "").trim().toUpperCase();

  // Prefer building the official URL from a valid NCT identifier.
  if (/^NCT\d{8}$/.test(id)) {
    return `https://clinicaltrials.gov/study/${id}`;
  }

  // Validate a URL supplied by the API, if the NCT ID is unavailable.
  const suppliedUrl = trial?.url || trial?.source_url;

  if (typeof suppliedUrl === "string") {
    try {
      const parsedUrl = new URL(suppliedUrl.trim());
      const validHost = parsedUrl.hostname.toLowerCase() === "clinicaltrials.gov";
      const validPath = /^\/study\/NCT\d{8}$/i.test(parsedUrl.pathname);

      if (parsedUrl.protocol === "https:" && validHost && validPath) {
        return parsedUrl.href;
      }
    } catch {
      // Ignore malformed URLs.
    }
  }

  return null;
}

function getValidatedSourceUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;

  try {
    const parsedUrl = new URL(value.trim());

    if (
      parsedUrl.protocol === "https:" &&
      parsedUrl.hostname &&
      !parsedUrl.username &&
      !parsedUrl.password
    ) {
      return parsedUrl.href;
    }
  } catch {
    // Ignore malformed or unsafe source URLs.
  }

  return null;
}

function asArray(value) {

  return Array.isArray(value) ? value : [];

}



function normalizeCriteria(data) {

  const grouped = {

    inclusion: [],

    exclusion: [],

    unknown: [],

  };



  // Support criterion results returned as a flat list.

  const flat =

    data?.criterion_results ||

    data?.judged_criteria ||

    data?.eligibility_assessment?.criteria ||

    (Array.isArray(data?.criteria) ? data.criteria : null);



  if (Array.isArray(flat)) {

    flat.forEach((item) => {

      if (!item) return;



      const type = String(

        item.criterion_type || item.type || ""

      ).toUpperCase();



      if (type.includes("EXCLUSION")) {

        grouped.exclusion.push(item);

      } else if (type.includes("INCLUSION")) {

        grouped.inclusion.push(item);

      } else {

        grouped.unknown.push(item);

      }

    });



    return grouped;

  }



  // Support criteria grouped into inclusion/exclusion arrays.

  const criteria =

    data?.criteria ||

    data?.eligibility_criteria ||

    data?.eligibility_assessment ||

    {};



  const inclusion = asArray(

    criteria.inclusion ||

      criteria.inclusion_criteria ||

      data?.inclusion_criteria

  );



  const exclusion = asArray(

    criteria.exclusion ||

      criteria.exclusion_criteria ||

      data?.exclusion_criteria

  );



  grouped.inclusion = inclusion;

  grouped.exclusion = exclusion;



  return grouped;

}



function CriterionItem({ item, index }) {

  const isString = typeof item === "string";



  const criterion = isString

    ? item

    : item?.criterion_quote ||

      item?.criterion ||

      item?.text ||

      item?.description ||

      "Criterion text unavailable";



  const impact = isString

    ? "UNKNOWN"

    : String(item?.impact || "UNKNOWN").toUpperCase();



  const evidence = isString

    ? ""

    : item?.patient_evidence ||

      item?.patient_evidence_quote ||

      item?.evidence ||

      "";



  const explanation = isString ? "" : item?.explanation || "";

  const source = isString ? "" : item?.source || "";
  const sourceUrl = isString
    ? null
    : getValidatedSourceUrl(item?.source_url || item?.url);



  return (

    <details className="criterion-item" open>

      <summary className="criterion-summary">

        <span className="criterion-title">{criterion}</span>



        <span className={`criterion-impact ${getImpactClass(impact)}`}>

          {impact}

        </span>

      </summary>



      <div className="criterion-content">

        <div className="criterion-field">

          <strong>Criterion</strong>

          <p>{criterion}</p>

        </div>



        <div className="criterion-field">

          <strong>Patient evidence</strong>

          <p>

            {evidence ||

              "No direct patient evidence was returned for this criterion."}

          </p>

        </div>



        <div className="criterion-field">

          <strong>Explanation</strong>

          <p>

            {explanation ||

              "No additional explanation was returned."}

          </p>

        </div>



        {(source || sourceUrl) && (

          <div className="criterion-field">

            <strong>Evidence source</strong>

            <p>
              {source || "Source record"}
              {sourceUrl && (
                <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
                  Open source ↗
                </a>
              )}
            </p>

          </div>

        )}

      </div>

    </details>

  );

}



function CriteriaSection({ title, items }) {

  return (

    <section className="criteria-section">

      <h4>

        {title} ({items.length})

      </h4>



      {items.length ? (

        <div className="criteria-list">

          {items.map((item, index) => (

            <CriterionItem

              key={`${title}-${index}`}

              item={item}

              index={index}

            />

          ))}

        </div>

      ) : (

        <p className="trial-muted">

          No {title.toLowerCase()} were returned in the API response.

        </p>

      )}

    </section>

  );

}



function EvidenceList({ items, title }) {
  if (!Array.isArray(items) || items.length === 0) {
    return <p className="trial-muted">No supporting evidence returned.</p>;
  }



  return (

    <section className="trial-evidence-group">

      <h4 className="trial-evidence-heading">{title}</h4>



      <ul className="trial-evidence-list">

        {items
          .filter((item) =>
            typeof item === "string"
              ? item.trim()
              : item &&
                (item.text ||
                  item.criterion_quote ||
                  item.criterion ||
                  item.description ||
                  item.excerpt)
          )
          .map((item, index) => {

          const text =

            typeof item === "string"

              ? item

              : item?.text ||

                item?.criterion_quote ||

                item?.criterion ||

                item?.description ||

                item?.excerpt ||

                "";



          const url =

            typeof item === "object"

              ? getValidatedSourceUrl(item?.url || item?.source_url)

              : null;



          return (

            <li className="trial-evidence-item" key={`${index}-${text}`}>

              {text}



              {typeof url === "string" &&

                /^https?:\/\//i.test(url) && (

                  <>

                    {" "}

                    <a

                      href={url}

                      target="_blank"

                      rel="noopener noreferrer"

                    >

                      Open source ↗

                    </a>

                  </>

                )}

            </li>

          );

        })}

      </ul>

    </section>

  );

}



export default function TrialCard({

  match,

  trial,

  index = 0,

}) {

  // App.jsx passes `match`; `trial` is also supported.

  const received = match || trial;



  if (!received || typeof received !== "object") {

    return null;

  }



  const data =

    received.trial && typeof received.trial === "object"

      ? { ...received.trial, ...received }

      : received;



  const {

    nct_id,

    title,

    status,

    phases,

    sponsor,

    conditions,

    verdict,

    relevance_score,

    summary,

    passages,

    locations,

    dropped_unverified,

  } = data;



  const criteria = normalizeCriteria(data);

  const trialId = nct_id || "NCT ID unavailable";

  const trialTitle = title || "Untitled clinical trial";

  const verdictText =
    {
      ELIGIBLE: "Likely eligible",
      POSSIBLY_ELIGIBLE: "Possibly eligible",
      COULD_NOT_ASSESS: "Could not assess",
      EXCLUDED: "Excluded",
    }[verdict] || formatValue(verdict) || "Needs verification";

  const score = formatScore(relevance_score);
  const numericScore = Number(relevance_score);
  const scorePercent = Number.isFinite(numericScore)
    ? Math.max(0, Math.min(100, Math.round(numericScore <= 1 ? numericScore * 100 : numericScore)))
    : 0;

  const officialUrl = getOfficialUrl(data);
  const evidenceItems = asArray(passages).filter((item) => {
    if (typeof item === "string") return item.trim().length > 0;
    if (!item || typeof item !== "object") return false;

    return Boolean(
      item.text ||
        item.criterion_quote ||
        item.criterion ||
        item.description ||
        item.excerpt
    );
  });



  return (

    <article className="trial-card">

      <div className="trial-card-topline">

        <div className="trial-card-number">

          {String(index + 1).padStart(2, "0")}

        </div>



        <div className="trial-card-tags">

          {status && (

            <span className="trial-status">

              <span className="status-dot" />

              {status}

            </span>

          )}



          {formatValue(phases) && (

            <span className="trial-phase">

              {formatValue(phases)}

            </span>

          )}

        </div>



        {score !== null && (

          <div className="trial-score">

            <span className="trial-score-value">{score}</span>

            <span className="trial-score-label">Retrieval similarity</span>
            <div
              className="trial-score-track"
              role="progressbar"
              aria-label="Trial match score"
              aria-valuemin="0"
              aria-valuemax="100"
              aria-valuenow={scorePercent}
            >
              <span style={{ width: `${scorePercent}%` }} />
            </div>
            <span className="trial-score-note">
              Retrieval relevance, not probability of eligibility
            </span>

          </div>

        )}

      </div>



      <div className="trial-card-body">

        <div className="trial-id">
          {/^NCT\d{8}$/i.test(String(nct_id || "").trim()) ? (
            <a
              className="nct-link"
              href={officialUrl || `https://clinicaltrials.gov/study/${String(nct_id).trim().toUpperCase()}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(event) => event.stopPropagation()}
              aria-label={`Open clinical trial ${trialId} on ClinicalTrials.gov`}
            >
              {trialId} <span aria-hidden="true">↗</span>
            </a>
          ) : (
            trialId
          )}
        </div>



        <h3 className="trial-title">{trialTitle}</h3>



        {summary && (

          <p className="trial-summary">{formatValue(summary)}</p>

        )}



        <div className="trial-meta-grid">

          {formatValue(sponsor) && (

            <div className="trial-meta-item">

              <span className="trial-meta-label">SPONSOR</span>

              <span className="trial-meta-value">
                {formatValue(sponsor)}

              </span>

            </div>
          )}

          {formatValue(conditions) && (

            <div className="trial-meta-item">

              <span className="trial-meta-label">CONDITIONS</span>

              <span className="trial-meta-value">

                {formatValue(conditions)}

              </span>

            </div>

          )}



          {formatValue(locations) && (

            <div className="trial-meta-item">

              <span className="trial-meta-label">LOCATIONS</span>

              <span className="trial-meta-value">

                {formatValue(locations)}

              </span>

            </div>

          )}

        </div>



        <div className="trial-verdict-section">

          <div className="trial-verdict-label">

            ELIGIBILITY ASSESSMENT

          </div>



          <span

            className={`trial-verdict ${getVerdictClass(verdictText)}`}

          >

            {verdictText}

          </span>

        </div>



        <details className="trial-details" open>

          <summary>View inclusion and exclusion criteria</summary>



          <div className="trial-details-content">

            <CriteriaSection

              title="Inclusion criteria"

              items={criteria.inclusion}

            />



            <CriteriaSection

              title="Exclusion criteria"

              items={criteria.exclusion}

            />



            {criteria.unknown.length > 0 && (

              <CriteriaSection

                title="Unclassified criteria"

                items={criteria.unknown}

              />

            )}

          </div>

        </details>



        {(

          <details className="trial-details" open>

            <summary>

              View supporting evidence ({evidenceItems.length})

            </summary>



            <div className="trial-details-content">

              <EvidenceList

                title="Retrieved evidence"

                items={evidenceItems}

              />

            </div>

          </details>

        )}



        {Array.isArray(dropped_unverified) &&

          dropped_unverified.length > 0 && (

            <details className="trial-details">

              <summary>

                Items requiring verification ({dropped_unverified.length})

              </summary>



              <div className="trial-details-content">

                <EvidenceList

                  title="Unverified information"

                  items={dropped_unverified}

                />

              </div>

            </details>

          )}

      </div>



      <footer className="trial-card-footer">

        <span className="trial-footer-note">

          Verify eligibility with the official study record.

        </span>



        {officialUrl ? (

          <a

            className="trial-source-link"

            href={officialUrl}

            target="_blank"

            rel="noopener noreferrer"

          >

            Official study ↗

          </a>

        ) : (

          <span className="trial-source-unavailable">

            Valid study link unavailable

          </span>

        )}

      </footer>

    </article>

  );

}
