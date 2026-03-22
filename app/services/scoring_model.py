
 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
 
# ── singleton vectorizer ──────────────────────────────────────────────────────
# Fitted lazily on first call with a broad vocabulary so subsequent calls
# only need transform() which is ~5x faster than fit_transform().
_vectorizer: TfidfVectorizer | None = None
_vocab_fitted = False
 
 
def _get_vectorizer() -> TfidfVectorizer:
    global _vectorizer, _vocab_fitted
    if _vectorizer is None:
        _vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=8000,      # caps vocab size for speed
            sublinear_tf=True,      # log(tf)+1 — better for short texts
        )
    return _vectorizer
 
 
def structured_skill_score(user: dict, job: dict, weights: dict) -> tuple:
    score = 0
    missing_skills = {}
 
    for category, weight in weights.items():
        user_set = set(user.get(category, []))
        job_set  = set(job.get(category,  []))
 
        if not job_set:
            continue
 
        matched        = user_set & job_set
        score         += (len(matched) / len(job_set)) * weight * 100
        missing_skills[category] = list(job_set - user_set)
 
    return round(score, 2), missing_skills
 
 
def semantic_similarity(resume_text: str, job_text: str) -> float:
    global _vocab_fitted
 
    vect = _get_vectorizer()
 
    if not _vocab_fitted:
        # First call: fit on both documents together
        vectors = vect.fit_transform([resume_text, job_text])
        _vocab_fitted = True
    else:
        try:
            vectors = vect.transform([resume_text, job_text])
        except Exception:
            # Vocabulary miss (unknown tokens only) — re-fit
            vectors = vect.fit_transform([resume_text, job_text])
 
    sim = cosine_similarity(vectors[0], vectors[1])[0][0]
    return round(float(sim) * 100, 2)
 
 
def hybrid_match_score(structured: float, semantic: float, alpha: float = 0.67) -> float:
    return round((alpha * structured) + ((1 - alpha) * semantic), 2)
 
 
def gap_severity(score: float) -> str:
    if score >= 80:
        return "Low"
    elif score >= 60:
        return "Medium"
    elif score >= 30:
        return "High"
    else:
        return "Critical"

    return