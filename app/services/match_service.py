from app.services.scoring_model import (
    structured_skill_score,
    semantic_similarity,
    hybrid_match_score,
    gap_severity
)

WEIGHTS = {
    "technical": 0.55,
    "tools": 0.25,
    "soft": 0.20
}

def run_matching_pipeline(user_profile, job_profile, resume_text, job_text):
    structured_score, missing_skills = structured_skill_score(
        user_profile, job_profile, WEIGHTS
    )

    semantic_score = semantic_similarity(resume_text, job_text)

    final_score = hybrid_match_score(structured_score, semantic_score)

    severity = gap_severity(final_score)

    return {
        "final_match_score": final_score,
        "structured_score": structured_score,
        "semantic_score": semantic_score,
        "gap_severity": severity,
        "missing_skills": missing_skills
    }
