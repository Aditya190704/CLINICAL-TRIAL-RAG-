"""For trials with PubMed references, fetch open-access abstracts via the PMC BioC API."""
import json
import time
import requests
from app.config import settings

IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
BIOC = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{}/unicode"


def pmid_to_pmcid(pmid: str) -> str | None:
    r = requests.get(IDCONV, params={"ids": pmid, "format": "json", "tool": "trial-rag",
                                     "email": "you@example.com"}, timeout=30)
    recs = r.json().get("records", [])
    return recs[0].get("pmcid") if recs else None


def abstract_from_bioc(pmcid: str) -> dict | None:
    r = requests.get(BIOC.format(pmcid), timeout=60)
    if r.status_code != 200:
        return None
    data = r.json()
    docs = data[0]["documents"] if isinstance(data, list) else data["documents"]
    passages = docs[0]["passages"]
    title = next((p["text"] for p in passages if p["infons"].get("section_type") == "TITLE"), "")
    abstract = " ".join(p["text"] for p in passages if p["infons"].get("section_type") == "ABSTRACT")
    return {"pmcid": pmcid, "title": title, "abstract": abstract} if abstract else None


if __name__ == "__main__":
    path = settings.processed_dir / "trials.json"
    trials = json.load(open(path, encoding="utf-8"))
    n = 0
    for t in trials:
        for pmid in t["pmids"][:2]:
            pmcid = pmid_to_pmcid(pmid)
            time.sleep(0.4)
            if pmcid and (doc := abstract_from_bioc(pmcid)):
                t["publications"].append({"pmid": pmid, **doc})
                n += 1
            time.sleep(0.4)
    json.dump(trials, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Attached {n} PMC abstracts")