"""Download ~500 recruiting trials across 12 therapeutic areas via ClinicalTrials.gov API v2."""
import json
import re
import time
from collections import Counter

import requests
from app.config import settings

API = "https://clinicaltrials.gov/api/v2/studies"
AREAS = ["breast cancer", "lung cancer", "colorectal cancer", "type 2 diabetes", "heart failure",
         "chronic kidney disease", "rheumatoid arthritis", "multiple sclerosis", "asthma COPD",
         "Alzheimer disease", "depression", "hepatitis HIV infection"]
PER_AREA = 42  # 12 x 42


def parse_age(s: str | None):
    if not s:
        return None
    m = re.match(r"(\d+(?:\.\d+)?)\s*(year|month|week|day)", s.lower())
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2)
    return v / {"year": 1, "month": 12, "week": 52, "day": 365}[unit]


def flatten(study: dict) -> dict | None:
    p = study.get("protocolSection", {})
    ident, st, desc = p.get("identificationModule", {}), p.get("statusModule", {}), p.get("descriptionModule", {})
    el, dm, cm = p.get("eligibilityModule", {}), p.get("designModule", {}), p.get("conditionsModule", {})
    ai, cl, sp = p.get("armsInterventionsModule", {}), p.get("contactsLocationsModule", {}), p.get("sponsorCollaboratorsModule", {})
    refs = p.get("referencesModule", {}).get("references", [])
    if not el.get("eligibilityCriteria") or not desc.get("briefSummary"):
        return None
    return {
        "nct_id": ident["nctId"],
        "title": ident.get("briefTitle", ""),
        "official_title": ident.get("officialTitle", ""),
        "status": st.get("overallStatus", ""),
        "phases": dm.get("phases", []),
        "study_type": dm.get("studyType", ""),
        "conditions": cm.get("conditions", []),
        "keywords": cm.get("keywords", []),
        "brief_summary": desc["briefSummary"],
        "interventions": [i.get("name", "") for i in ai.get("interventions", [])],
        "eligibility_text": el["eligibilityCriteria"],
        "sex": el.get("sex", "ALL"),
        "min_age": el.get("minimumAge"), "max_age": el.get("maximumAge"),
        "min_age_years": parse_age(el.get("minimumAge")), "max_age_years": parse_age(el.get("maximumAge")),
        "healthy_volunteers": el.get("healthyVolunteers"),
        "sponsor": sp.get("leadSponsor", {}).get("name"),
        "locations": [f"{l.get('facility','')}, {l.get('city','')}, {l.get('country','')}".strip(", ")
                      for l in cl.get("locations", [])[:5]],
        "pmids": [r["pmid"] for r in refs if r.get("pmid")],
        "publications": [],
    }


def fetch_area(area: str, want: int, seen: set) -> list[dict]:
    out, token = [], None
    while len(out) < want:
        params = {"query.cond": area, "filter.overallStatus": "RECRUITING", "pageSize": 50, "format": "json"}
        if token:
            params["pageToken"] = token
        r = requests.get(API, params=params, timeout=60)
        r.raise_for_status()
        j = r.json()
        for s in j.get("studies", []):
            rec = flatten(s)
            if rec and rec["nct_id"] not in seen:
                seen.add(rec["nct_id"])
                out.append(rec)
                if len(out) >= want:
                    break
        token = j.get("nextPageToken")
        if not token:
            break
        time.sleep(0.3)
    return out


def profile_data(trials: list[dict]):
    print(f"\nTrials: {len(trials)}")
    print("Phases:", Counter(p for t in trials for p in (t["phases"] or ["NA"])).most_common())
    print("Sex:", Counter(t["sex"] for t in trials))
    print("Has explicit exclusion section:",
          sum(bool(re.search(r"exclusion criteria", t["eligibility_text"], re.I)) for t in trials))
    lens = sorted(len(t["eligibility_text"]) for t in trials)
    print(f"Eligibility chars  median={lens[len(lens)//2]}  max={lens[-1]}")


if __name__ == "__main__":
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