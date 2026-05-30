"""
app/routes/match.py
────────────────────────────────────────────────────────────────────────────────
POST /match  — Run the full Skillify matching pipeline for a single
               candidate ↔ job pair and return scores + optional LIME
               explanation.

Request body (JSON)
───────────────────
{
  "user": {
    "technical": ["python", "react"],
    "tools":     ["git", "docker"],
    "soft":      ["communication"]
  },
  "job": {
    "technical": ["python", "react", "node.js"],
    "tools":     ["git", "docker", "kubernetes"],
    "soft":      ["teamwork"]
  },
  "resume_text": "Full resume text as a plain string ...",
  "job_text":    "Full job description as a plain string ...",
  "explain":     true          ← optional, defaults to true
}

Response body (JSON)
────────────────────
{
  "final_match_score":       72.4,
  "structured_score":        65.3,
  "semantic_score":          87.1,
  "gap_severity":            "Medium",
  "missing_skills": {
    "technical": ["node.js"],
    "tools":     ["kubernetes"],
    "soft":      ["teamwork"]
  },
  "semantic_keyword_impact": {
    "python":  0.082341,
    "react":   0.071205,
    "docker":  0.063018,
    "sales":  -0.031200    ← negative = hurts the match
  }
}

Notes
─────
  • Set "explain": false to skip LIME and get a ~2-3s faster response.
    Useful for bulk scoring where explanations aren't needed.
  • "semantic_keyword_impact" is always present in the response (empty dict {}
    when explain=false or LIME fails), so frontend code can check it safely.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.match_service import run_matching_pipeline

router = APIRouter()


# ── Request schema ────────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    """
    Payload for POST /match.

    Fields
    ------
    user        : candidate's skill profile (technical / tools / soft lists)
    job         : job's required skill profile (same shape)
    resume_text : raw resume text — used for TF-IDF semantic score and LIME
    job_text    : raw job description text
    explain     : if True (default), include LIME keyword-impact explanation.
                  Set to False for faster bulk scoring without explanations.
    """
    user:        dict = Field(...,  description="Candidate skill profile")
    job:         dict = Field(...,  description="Job required skill profile")
    resume_text: str  = Field(...,  description="Raw resume text")
    job_text:    str  = Field(...,  description="Raw job description text")
    explain:     Optional[bool] = Field(
        default=True,
        description=(
            "Set to false to skip LIME explanation (~2-3s faster). "
            "semantic_keyword_impact will be {} in the response."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user": {
                    "technical": ["python", "react", "docker"],
                    "tools":     ["git"],
                    "soft":      ["communication"],
                },
                "job": {
                    "technical": ["python", "react", "node.js", "docker"],
                    "tools":     ["git", "kubernetes"],
                    "soft":      ["teamwork"],
                },
                "resume_text": "Python developer with 2 years experience in React and Docker...",
                "job_text":    "We are looking for a Python developer skilled in React, Node.js...",
                "explain":     True,
            }
        }
    }


# ── Response schema ───────────────────────────────────────────────────────────

class MatchResponse(BaseModel):
    """
    Response from POST /match.

    Fields
    ------
    final_match_score       : hybrid weighted score (0-100)
    structured_score        : hard skill overlap score (0-100)
    semantic_score          : TF-IDF cosine similarity × 100 (0-100)
    gap_severity            : "Low" | "Medium" | "High"
    missing_skills          : skills the candidate lacks per category
    semantic_keyword_impact : LIME word → weight dict (empty when explain=False)
    """
    final_match_score:       float
    structured_score:        float
    semantic_score:          float
    gap_severity:            str
    missing_skills:          dict
    semantic_keyword_impact: dict


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/match",
    response_model=MatchResponse,
    summary="Match a candidate to a job",
    description=(
        "Runs the full Skillify scoring pipeline: structured skill overlap, "
        "TF-IDF semantic similarity, hybrid blend, and optional LIME explanation "
        "of which words drove the semantic score."
    ),
)
def match_user(request: MatchRequest) -> MatchResponse:
    """
    Score a candidate against a job description and optionally explain
    which words in their resume most influenced the semantic match score.
    """
    result = run_matching_pipeline(
        user_profile=request.user,
        job_profile=request.job,
        resume_text=request.resume_text,
        job_text=request.job_text,
        explain=request.explain if request.explain is not None else True,
    )
    return MatchResponse(**result)
