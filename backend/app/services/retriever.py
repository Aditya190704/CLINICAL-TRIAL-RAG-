from collections import defaultdict
from dataclasses import dataclass, field

from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import Namespace

from app.config import settings
from app.services.embeddings import embed
from app.services.trial_store import chunks

aiplatform.init(project=settings.gcp_project, location=settings.gcp_location)
_endpoint = None


def _get_endpoint():
    global _endpoint
    if _endpoint is None:
        _endpoint = aiplatform.MatchingEngineIndexEndpoint(settings.index_endpoint_id)
    return _endpoint


@dataclass
class Candidate:
    nct_id: str
    rrf: float = 0.0
    best_sim: float = 0.0
    chunk_ids: list[str] = field(default_factory=list)


def retrieve(queries: list[str]) -> list[Candidate]:
    """Run every query, fuse chunk hits into trial-level scores with Reciprocal Rank Fusion."""
    vectors = embed(queries, task_type="RETRIEVAL_QUERY")
    result = _get_endpoint().find_neighbors(
        deployed_index_id=settings.deployed_index_id,
        queries=vectors,
        num_neighbors=settings.top_k_chunks,
        filter=[Namespace("status", ["RECRUITING"], [])],
    )
    meta = chunks()
    cands: dict[str, Candidate] = defaultdict(lambda: Candidate(nct_id=""))
    for neighbours in result:
        seen_in_query: set[str] = set()
        for rank, n in enumerate(neighbours):
            nct = meta[n.id]["nct_id"]
            c = cands[nct]
            c.nct_id = nct
            if n.id not in c.chunk_ids:
                c.chunk_ids.append(n.id)
            if nct not in seen_in_query:           # count a trial once per query (best chunk)
                c.rrf += 1.0 / (60 + rank)
                seen_in_query.add(nct)
            c.best_sim = max(c.best_sim, float(n.distance))   # dot product of unit vectors = cosine
    return sorted(cands.values(), key=lambda c: c.rrf, reverse=True)