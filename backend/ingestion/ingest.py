import json
from google.cloud import aiplatform
from google.cloud.aiplatform_v1.types import IndexDatapoint

from app.config import settings
from app.services.embeddings import embed
from app.services import gcs_store
from ingestion.chunker import chunk_trial

aiplatform.init(project=settings.gcp_project, location=settings.gcp_location)

if __name__ == "__main__":
    trials = json.load(open(settings.processed_dir / "trials.json", encoding="utf-8"))
    all_chunks = [c for t in trials for c in chunk_trial(t)]
    print(f"{len(trials)} trials -> {len(all_chunks)} chunks")

    vectors = embed([c["text"] for c in all_chunks], task_type="RETRIEVAL_DOCUMENT")
    status = {t["nct_id"]: t["status"] for t in trials}

    index = aiplatform.MatchingEngineIndex(settings.index_id)
    for i in range(0, len(all_chunks), 100):
        dps = [IndexDatapoint(
                   datapoint_id=c["id"], feature_vector=v,
                   restricts=[IndexDatapoint.Restriction(namespace="status", allow_list=[status[c["nct_id"]]])])
               for c, v in zip(all_chunks[i:i + 100], vectors[i:i + 100])]
        index.upsert_datapoints(datapoints=dps)
        print(f"upserted {min(i + 100, len(all_chunks))}/{len(all_chunks)}")

    meta = {c["id"]: {"nct_id": c["nct_id"], "type": c["type"], "text": c["text"]} for c in all_chunks}
    json.dump(meta, open(settings.processed_dir / "chunks.json", "w", encoding="utf-8"), ensure_ascii=False)
    if settings.gcs_bucket:
        for name in ("trials.json", "chunks.json"):
            uri = gcs_store.upload_file(settings.processed_dir / name, name)
            print("uploaded", uri)