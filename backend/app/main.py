import logging
import truststore
truststore.inject_into_ssl()
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import MatchRequest, MatchResponse
from app.services import pipeline
from app.services.trial_store import trials

logger = logging.getLogger(__name__)

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
    except PermissionError as e:
        logger.error(f"Permission error during trial matching: {e}")
        raise HTTPException(
            status_code=503,
            detail="Google Cloud access denied. Check BigQuery IAM permissions.",
        )
    except RuntimeError as e:
        logger.error(f"Runtime error during trial matching: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Retrieval error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error during trial matching: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error occurred while matching trials.",
        )