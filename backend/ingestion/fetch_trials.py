"""Download ~500 recruiting trials across 12 therapeutic areas via ClinicalTrials.gov API v2."""
import json
import re # use regular expressions to extract age and detect exclusion criteria
import time
from collections import Counter # count trials by phase, sex, etc

import requests # send HTTP request to clinicaltrials.gov API
from app.config import settings # read configuration settings for directories and API parameters
# https://clinicaltrials.gov/api/v2/studies/NCT04932928 - json example of a single trial response from the API v2
API = "https://clinicaltrials.gov/api/v2/studies"
AREAS = ["breast cancer", "lung cancer", "colorectal cancer", "type 2 diabetes", "heart failure",
         "chronic kidney disease", "rheumatoid arthritis", "multiple sclerosis", "asthma COPD",
         "Alzheimer disease", "depression", "hepatitis HIV infection"]
PER_AREA = 42  # 12 x 42 # we try to collect 42 unique trials per search query


def parse_age(s: str | None): # ClinicalTrials.gov can return age values in different units. Our Project Standardizes them into years.
    if not s:
        return None
    m = re.match(r"(\d+(?:\.\d+)?)\s*(year|month|week|day)", s.lower()) # this RE gives us two things Numeric age, unit for example 18 years
    if not m: # input doesnt match return None
        return None
    v, unit = float(m.group(1)), m.group(2)
    return v / {"year": 1, "month": 12, "week": 52, "day": 365}[unit] #year unchanged, month divide by 12, week divide by 52, day divide by 365 to convert to years


def flatten(study: dict) -> dict | None: # Takes one raw clinical trial response from the API and converts it into a clean Python dictionary.

    p = study.get("protocolSection", {}) # Gets the protocolSection from the API response, which contains the main clinical trial information.
    
    ident, st, desc = (
        p.get("identificationModule", {}),
        p.get("statusModule", {}),
        p.get("descriptionModule", {})
    ) # Extracts the trial's identification details, recruitment status, and description.

    el, dm, cm = (
        p.get("eligibilityModule", {}),
        p.get("designModule", {}),
        p.get("conditionsModule", {})
    ) # Extracts eligibility criteria, study design details, and medical conditions.

    ai, cl, sp = (
        p.get("armsInterventionsModule", {}),
        p.get("contactsLocationsModule", {}),
        p.get("sponsorCollaboratorsModule", {})
    ) # Extracts intervention details, study locations, and sponsor information.

    refs = p.get("referencesModule", {}).get("references", []) # Gets the trial's references, such as linked research publications; uses an empty list if unavailable.

    if not el.get("eligibilityCriteria") or not desc.get("briefSummary"): # Checks whether the trial has both eligibility criteria and a brief summary.
        return None  # Skips this trial if either required piece of information is missing.

    return { # Returns a cleaned dictionary containing the useful information for our project.
        # 21 fields are extracted from the API response and stored in a structured format.

        "nct_id": ident["nctId"],
        # Stores the unique ClinicalTrials.gov identifier of the trial.

        "title": ident.get("briefTitle", ""),
        # Stores the short title of the trial; uses an empty string if unavailable.

        "official_title": ident.get("officialTitle", ""),
        # Stores the official full title of the trial.

        "status": st.get("overallStatus", ""),
        # Stores the current recruitment or study status reported by the API.

        "phases": dm.get("phases", []),
        # Stores the clinical trial phases, if available.

        "study_type": dm.get("studyType", ""),
        # Stores the study type, such as interventional or observational.

        "conditions": cm.get("conditions", []),
        # Stores the medical conditions that the trial investigates.

        "keywords": cm.get("keywords", []),
        # Stores keywords associated with the trial.

        "brief_summary": desc["briefSummary"],
        # Stores the trial summary explaining its purpose.

        "interventions": [
            i.get("name", "") for i in ai.get("interventions", [])
        ],
        # Extracts the name of each intervention, such as a drug or treatment.

        "eligibility_text": el["eligibilityCriteria"],
        # Stores the complete eligibility criteria used later for patient-trial matching.

        "sex": el.get("sex", "ALL"),
        # Stores the sex eligibility requirement; defaults to ALL if not provided.

        "min_age": el.get("minimumAge"),
        # Stores the minimum age in its original API format.

        "max_age": el.get("maximumAge"),
        # Stores the maximum age in its original API format.

        "min_age_years": parse_age(el.get("minimumAge")),
        # Converts the minimum age into years using the parse_age() function.

        "max_age_years": parse_age(el.get("maximumAge")),
        # Converts the maximum age into years using the parse_age() function.

        "healthy_volunteers": el.get("healthyVolunteers"),
        # Stores whether healthy volunteers are allowed in the trial.

        "sponsor": sp.get("leadSponsor", {}).get("name"),
        # Extracts the name of the lead organization sponsoring the trial.

        "locations": [
            f"{l.get('facility', '')}, {l.get('city', '')}, {l.get('country', '')}".strip(", ")
            for l in cl.get("locations", [])[:5]
        ],
        # Creates readable location strings and keeps at most five study locations.

        "pmids": [r["pmid"] for r in refs if r.get("pmid")],
        # Collects PubMed IDs from references that contain a PMID.

        "publications": [],
        # Initializes an empty list for publication details that may be added later.
    }
    # Finishes returning the cleaned clinical trial record.


def fetch_area(area: str, want: int, seen: set) -> list[dict]: # Fetches clinical trials for one medical condition and returns valid, unique trial records.
    out, token = [], None # Creates an empty list for collected trials and initializes the pagination token.

    while len(out) < want:
        # Continues fetching trials until the requested count is reached or no more pages exist.

        params = {
            "query.cond": area,
            "filter.overallStatus": "RECRUITING",
            "pageSize": 50,
            "format": "json"
        }
        # Sets the search condition, recruiting status, page size, and response format.

        if token:
            params["pageToken"] = token
        # Adds the next-page token when the API has more results to return.

        r = requests.get(API, params=params, timeout=60)
        # Sends an HTTP GET request to ClinicalTrials.gov with these search parameters.

        r.raise_for_status()
        # Raises an error if the API request fails with an HTTP error status.

        j = r.json()
        # Converts the API's JSON response into a Python dictionary.

        for s in j.get("studies", []):
            # Iterates through the clinical studies returned on this page.

            rec = flatten(s)
            # Converts each raw study into a clean record using flatten().

            if rec and rec["nct_id"] not in seen:
                # Accepts only valid records whose trial IDs have not already been collected.

                seen.add(rec["nct_id"])
                # Adds the trial ID to the shared set to prevent duplicates across searches.

                out.append(rec)
                # Adds the cleaned trial record to this area's results.

                if len(out) >= want:
                    # Checks whether the requested number of trials has been collected.
                    break
                    # Stops processing the current page when the target is reached.

        token = j.get("nextPageToken")
        # Gets the token required to request the next page of API results.

        if not token:
            # Checks whether another page is available.
            break
            # Stops if the API has no more pages.

        time.sleep(0.3)
        # Waits briefly before requesting another page to avoid 429 http error from PUBLIC API - too many requests in a short time.

    return out
    # Returns the collected valid and unique trial records.

#prints summary of the downloaded trials, including counts of phases, sex distribution, and eligibility text length.
def profile_data(trials: list[dict]):
    print(f"\nTrials: {len(trials)}")
    print("Phases:", Counter(p for t in trials for p in (t["phases"] or ["NA"])).most_common())
    print("Sex:", Counter(t["sex"] for t in trials))
    print("Has explicit exclusion section:",
          sum(bool(re.search(r"exclusion criteria", t["eligibility_text"], re.I)) for t in trials))
    lens = sorted(len(t["eligibility_text"]) for t in trials)
    print(f"Eligibility chars  median={lens[len(lens)//2]}  max={lens[-1]}")


if __name__ == "__main__": # Runs this block only when fetch_trials.py is executed directly.
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    seen, trials = set(), []
    for area in AREAS:
        got = fetch_area(area, PER_AREA, seen)
        print(f"{area}: {len(got)}")
        trials.extend(got)
    trials = trials[:500]
    with open(settings.processed_dir / "trials.json", "w", encoding="utf-8") as f:
        json.dump(trials, f, ensure_ascii=False, indent=1)
    profile_data(trials)