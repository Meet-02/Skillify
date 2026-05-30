"""
app/services/match_service.py
────────────────────────────────────────────────────────────────────────────────
Orchestrates the full matching pipeline for Skillify:
  1. Structured skill overlap score  (hard skills, tools, soft skills)
  2. TF-IDF semantic similarity score
  3. Hybrid weighted blend
  4. Gap severity label
  5. Optional LIME explanation of the semantic score

Usage
─────
    from app.services.match_service import run_matching_pipeline

    result = run_matching_pipeline(
        user_profile = {"technical": ["python","react"], "tools": ["git"], "soft": ["communication"]},
        job_profile  = {"technical": ["python","react","node"], "tools": ["git","docker"], "soft": []},
        resume_text  = "...",
        job_text     = "...",
        explain      = True,       # set False to skip LIME and save ~2-3s
    )

    # result keys:
    #   final_match_score       – 0-100 float (hybrid)
    #   structured_score        – 0-100 float (hard skill overlap)
    #   semantic_score          – 0-100 float (TF-IDF cosine ×100)
    #   gap_severity            – "Low" | "Medium" | "High"
    #   missing_skills          – {"technical": [...], "tools": [...], "soft": [...]}
    #   semantic_keyword_impact – {"python": 0.082, "sales": -0.031, ...}
    #                             (only present when explain=True and texts provided)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from app.services.scoring_model import (
    structured_skill_score,
    semantic_similarity,
    hybrid_match_score,
    gap_severity,
    explain_semantic_match,
)

logger = logging.getLogger(__name__)

# Skill category weights — must sum to 1.0
WEIGHTS: dict[str, float] = {
    "technical": 0.55,
    "tools":     0.25,
    "soft":      0.20,
}


def run_matching_pipeline(
    user_profile: dict,
    job_profile:  dict,
    resume_text:  str,
    job_text:     str,
    explain:      bool = True,
) -> dict:
    """
    Run the full Skillify matching pipeline.

    Parameters
    ----------
    user_profile : skill profile extracted from the candidate's resume.
                   Shape: {"technical": [...], "tools": [...], "soft": [...]}
    job_profile  : skill profile extracted from the job description.
                   Same shape as user_profile.
    resume_text  : raw resume text used for TF-IDF semantic scoring and LIME.
    job_text     : raw job description text.
    explain      : if True (default), append a LIME explanation of which words
                   drove the semantic score under the "semantic_keyword_impact"
                   key. Set to False to skip LIME and save ~2-3s on Render.

    Returns
    -------
    dict with keys:
        final_match_score       (float)  – weighted hybrid score, 0-100
        structured_score        (float)  – hard-skill overlap score, 0-100
        semantic_score          (float)  – TF-IDF cosine similarity ×100
        gap_severity            (str)    – "Low" | "Medium" | "High"
        missing_skills          (dict)   – skills the candidate is missing per category
        semantic_keyword_impact (dict)   – LIME word weights (only when explain=True)
    """
    # ── 1. Structured skill overlap ───────────────────────────────────────────
    structured_score, missing_skills = structured_skill_score(
        user_profile, job_profile, WEIGHTS
    )

    # ── 2. Semantic similarity ────────────────────────────────────────────────
    semantic_score = semantic_similarity(resume_text, job_text)

    # ── 3. Hybrid blend ───────────────────────────────────────────────────────
    final_score = hybrid_match_score(structured_score, semantic_score)

    # ── 4. Gap severity label ─────────────────────────────────────────────────
    severity = gap_severity(final_score)

    # ── 5. Base result ────────────────────────────────────────────────────────
    result: dict = {
        "final_match_score": final_score,
        "structured_score":  structured_score,
        "semantic_score":    semantic_score,
        "gap_severity":      severity,
        "missing_skills":    missing_skills,
    }

    # ── 6. Optional LIME explanation ─────────────────────────────────────────
    if explain and resume_text and job_text:
        try:
            keyword_impact = explain_semantic_match(
                resume_text=resume_text,
                job_text=job_text,
                num_features=10,
                num_samples=300,
            )
            result["semantic_keyword_impact"] = keyword_impact
        except Exception as exc:
            # Never let LIME failure break the core matching result
            logger.warning("LIME explanation skipped due to error: %s", exc)
            result["semantic_keyword_impact"] = {}
    else:
        # Always include the key so the frontend can check without KeyError
        result["semantic_keyword_impact"] = {}

    return result
