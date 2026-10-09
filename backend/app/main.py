from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import MatchRequest, MatchResponse
from app.services import pipeline
from app.services.trial_store import trials

app = FastAPI(title="Clinical Trial Matcher")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "trials_indexed": len(trials())}


@app.post("/api/match", response_model=MatchResponse)
def match(req: MatchRequest):
    try:
        return pipeline.run(req.patient_case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))