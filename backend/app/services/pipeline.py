import re
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.schemas import MatchResponse, Passage, TrialMatch
from app.services.eligibility_judge import compute_verdict, judge
from app.services.patient_parser import parse_patient
from app.services.retriever import retrieve
from app.services.trial_store import chunks, trials

DISCLAIMER = ("Research decision-support only. Not medical advice. All eligibility reasoning is limited to "
              "the supplied case and the registry text; confirm with the trial's contacts before referral.")
PHI = re.compile(r"(\b\d{3}-\d{2}-\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b)")
ORDER = {"ELIGIBLE": 0, "POSSIBLY_ELIGIBLE": 1, "EXCLUDED": 2}


def run(case: str) -> MatchResponse:
    t0 = time.time()
    if PHI.search(case):
        raise ValueError("Possible identifiers (SSN / email / phone) detected. Please anonymise the case.")

    profile = parse_patient(case)
    candidates = retrieve([profile.search_query, case[:2000]])[: settings.candidates_to_judge]

    def work(c):
        trial = trials()[c.nct_id]
        crit, summary, dropped = judge(case, profile, trial)
        return c, trial, crit, summary, dropped

    with ThreadPoolExecutor(max_workers=len(candidates) or 1) as ex:
        judged = list(ex.map(work, candidates))

    judged = [(c, t, cr, s, d, compute_verdict(cr)) for c, t, cr, s, d in judged]
    judged.sort(key=lambda x: (ORDER[x[5]], -x[0].rrf))      # eligible first, then by relevance

    matches = []
    for i, (c, t, crit, summary, dropped, verdict) in enumerate(judged[: settings.final_results], 1):
        passages = [Passage(chunk_type=chunks()[cid]["type"], text=chunks()[cid]["text"][:700])
                    for cid in c.chunk_ids[:3]]
        matches.append(TrialMatch(
            rank=i, nct_id=t["nct_id"], title=t["title"], url=f"https://clinicaltrials.gov/study/{t['nct_id']}",
            status=t["status"], phases=t["phases"], conditions=t["conditions"][:6], sponsor=t.get("sponsor"),
            locations=t["locations"][:3], relevance_score=round(c.best_sim, 3), verdict=verdict,
            summary=summary, criteria=crit, dropped_unverified=dropped, passages=passages))

    return MatchResponse(patient_profile=profile, matches=matches, disclaimer=DISCLAIMER,
                         latency_seconds=round(time.time() - t0, 1))