from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def structured_skill_score(user, job, weights):
    score = 0
    missing_skills = {}

    for category, weight in weights.items():
        user_set = set(user.get(category, []))
        job_set = set(job.get(category, []))

        if not job_set:
            continue

        matched = user_set.intersection(job_set)
        category_score = (len(matched) / len(job_set)) * weight * 100
        score += category_score

        missing_skills[category] = list(job_set - user_set)

    return round(score, 2), missing_skills


def semantic_similarity(resume_text, job_text):
    vectorizer = TfidfVectorizer(stop_words="english")
    vectors = vectorizer.fit_transform([resume_text, job_text])
    similarity = cosine_similarity(vectors[0], vectors[1])[0][0]
    return round(similarity * 100, 2)


def hybrid_match_score(structured, semantic, alpha=0.67):
    return round((alpha * structured) + ((1 - alpha) * semantic), 2)


def gap_severity(score):
    if score >= 80:
        return "Low"
    elif score >= 60:
        return "Medium"
    return "High"
