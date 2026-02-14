from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict
from app.services.match_service import run_matching_pipeline

router = APIRouter()

class MatchRequest(BaseModel):
    user: dict
    job: dict
    resume_text: str
    job_text: str

@router.post("/match")
def match_user(request: MatchRequest):
    result = run_matching_pipeline(
        user_profile=request.user,
        job_profile=request.job,
        resume_text=request.resume_text,
        job_text=request.job_text
    )
    return result
