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

# def run_matching_pipeline(user_profile, job_profile, resume_text, job_text):
#     structured_score, missing_skills = structured_skill_score(
#         user_profile, job_profile, WEIGHTS
#     )

#     semantic_score = semantic_similarity(resume_text, job_text)

#     final_score = hybrid_match_score(structured_score, semantic_score)

#     severity = gap_severity(final_score)

#     return {
#         "final_match_score": final_score,
#         "structured_score": structured_score,
#         "semantic_score": semantic_score,
#         "gap_severity": severity,
#         "missing_skills": missing_skills
#     }


from app.services.scraper_service import get_jobs   # ← the only import needed

def run_matching_pipeline(db, user_id, domain, city, user_profile,
                          job_profile, resume_text, job_text):

    # 1. Pull the hybrid job list (50% API + 50% scraped, de-duped)
    jobs = get_jobs(
        db=db,
        user_id=user_id,
        domain=domain,
        city=city,
        max_jobs=40,
    )

    # 2. Run your existing scoring logic against each job's description
    results = []
    for job in jobs:
        score_data = _score_single_job(
            user_profile=user_profile,
            job_profile=job_profile,
            resume_text=resume_text,
            job_text=job.get("description", ""),   # Unified Schema field
        )
        results.append({**job, **score_data})

    return results


def _score_single_job(user_profile, job_profile, resume_text, job_text):
    from app.services.scoring_model import (
        structured_skill_score, semantic_similarity,
        hybrid_match_score, gap_severity,
    )
    WEIGHTS = {"technical": 0.55, "tools": 0.25, "soft": 0.20}
    structured_score, missing_skills = structured_skill_score(
        user_profile, job_profile, WEIGHTS
    )
    semantic_score = semantic_similarity(resume_text, job_text)
    final_score = hybrid_match_score(structured_score, semantic_score)
    return {
        "final_match_score": final_score,
        "gap_severity":      gap_severity(final_score),
        "missing_skills":    missing_skills,
    }