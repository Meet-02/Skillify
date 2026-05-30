"""
app/services/scoring_model.py
────────────────────────────────────────────────────────────────────────────────
Core scoring primitives for Skillify's matching engine, plus LIME-based
semantic explanation.

Public API
──────────
  structured_skill_score(user, job, weights)  → (score, missing_skills)
  semantic_similarity(resume_text, job_text)  → float
  hybrid_match_score(structured, semantic)    → float
  gap_severity(score)                         → str
  explain_semantic_match(resume_text,         → dict[str, float]
                         job_text,
                         num_features,
                         num_samples)

LIME Implementation Notes
─────────────────────────
LimeTextExplainer does not accept a `mode='regression'` kwarg in the installed
version. Instead we use the standard classifier mode with two pseudo-classes:
  index 0 → "no_match"  (probability = 1 − cosine_sim)
  index 1 → "match"     (probability = cosine_sim)

explain_instance is called with labels=[1], so the returned weights reflect
each word's contribution to the "match" class — equivalent to a regression
explanation over the [0, 1] cosine similarity range.
Positive weight → word boosts the match.  Negative → word hurts it.

num_samples=300 ≈ 0.8s on a fast machine, ~2-3s on Render free-tier CPU.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURED SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def structured_skill_score(
    user: dict,
    job:  dict,
    weights: dict,
) -> tuple:
    """
    Compare user skill profile against job skill profile, category by category.

    Parameters
    ----------
    user    : {"technical": [...], "tools": [...], "soft": [...]}
    job     : same shape
    weights : {"technical": 0.55, "tools": 0.25, "soft": 0.20}

    Returns
    -------
    (score: float, missing_skills: dict)
    """
    score: float = 0.0
    missing_skills: dict = {}

    for category, weight in weights.items():
        user_set = set(s.lower() for s in user.get(category, []))
        job_set  = set(s.lower() for s in job.get(category,  []))

        if not job_set:
            continue

        matched = user_set & job_set
        category_score = (len(matched) / len(job_set)) * weight * 100
        score += category_score
        missing_skills[category] = sorted(job_set - user_set)

    return round(score, 2), missing_skills


# ═══════════════════════════════════════════════════════════════════════════════
# SEMANTIC SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def semantic_similarity(resume_text: str, job_text: str) -> float:
    """TF-IDF cosine similarity between resume and job text. Returns 0-100."""
    if not resume_text or not job_text:
        return 0.0
    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        vectors = vectorizer.fit_transform([resume_text, job_text])
        sim = cosine_similarity(vectors[0], vectors[1])[0][0]
        return round(float(sim) * 100, 2)
    except Exception as exc:
        logger.warning("semantic_similarity failed: %s", exc)
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# HYBRID SCORE & SEVERITY
# ═══════════════════════════════════════════════════════════════════════════════

def hybrid_match_score(
    structured: float,
    semantic:   float,
    alpha:      float = 0.67,
) -> float:
    """
    Weighted blend: alpha * structured + (1-alpha) * semantic.
    alpha=0.67 prioritises hard skill overlap over semantic similarity.
    """
    return round((alpha * structured) + ((1 - alpha) * semantic), 2)


def gap_severity(score: float) -> str:
    """Human-readable gap label based on final match score."""
    if score >= 80:
        return "Low"
    elif score >= 60:
        return "Medium"
    return "High"


# ═══════════════════════════════════════════════════════════════════════════════
# LIME EXPLANATION
# ═══════════════════════════════════════════════════════════════════════════════

def explain_semantic_match(
    resume_text:  str,
    job_text:     str,
    num_features: int = 10,
    num_samples:  int = 300,
) -> dict:
    """
    Use LIME to explain which words in `resume_text` most influenced the
    TF-IDF cosine similarity score against `job_text`.

    Parameters
    ----------
    resume_text  : candidate's resume as plain text
    job_text     : job description as plain text
    num_features : number of top words to return in the explanation (default 10)
    num_samples  : LIME perturbation samples — higher = more stable but slower.
                   300 ≈ 0.8s on a fast CPU, ~2-3s on Render free tier.

    Returns
    -------
    dict[str, float]
        Word → LIME weight.
        Positive weight = word boosts semantic match score.
        Negative weight = word hurts semantic match score.

        Example:
            {"python": 0.082, "react": 0.071, "sales": -0.031}

        Returns {} if either text is empty, too short, or LIME fails.

    How it works
    ────────────
    LimeTextExplainer operates in classification mode. We wrap cosine similarity
    as a 2-class probability vector:
        P("match")    = cosine_sim(perturbed_resume, job_text)
        P("no_match") = 1 - P("match")

    By requesting label=1 ("match"), LIME's linear surrogate gives us the
    marginal contribution of each word to the similarity score — identical in
    interpretation to a regression explanation on the raw similarity value.

    Edge cases handled
    ──────────────────
    - Empty / whitespace-only texts → returns {}
    - Texts shorter than 3 words    → returns {} (LIME needs tokens to mask)
    - LIME sends empty perturbed strings (all-words-masked) → treated as sim=0
    - TfidfVectorizer raises on degenerate text → treated as sim=0
    - lime not installed            → logs error, returns {}
    """
    # ── Guard: texts must be non-empty and long enough to perturb ────────────
    if not resume_text or not job_text:
        return {}

    clean_resume = resume_text.strip()
    clean_job    = job_text.strip()

    if len(clean_resume.split()) < 3 or len(clean_job.split()) < 2:
        logger.debug("explain_semantic_match: texts too short, skipping LIME")
        return {}

    # ── Lazy import keeps startup fast when explain=False ────────────────────
    try:
        from lime.lime_text import LimeTextExplainer
    except ImportError:
        logger.error(
            "lime is not installed. Add 'lime' to requirements.txt and redeploy."
        )
        return {}

    # ── Internal prediction function ─────────────────────────────────────────
    # LIME calls this repeatedly with lists of perturbed resume strings.
    # Must return np.ndarray of shape (n_texts, 2) with float values in [0, 1].
    def _predict(texts: list) -> np.ndarray:
        rows = []
        for t in texts:
            # LIME sometimes sends empty strings when it masks every token
            if not t or not t.strip() or len(t.split()) < 2:
                rows.append([1.0, 0.0])   # sim = 0 → all weight on "no_match"
                continue
            try:
                vec = TfidfVectorizer(stop_words="english")
                mat = vec.fit_transform([t, clean_job])
                sim = float(cosine_similarity(mat[0:1], mat[1:])[0][0])
                # Clamp to [0, 1] — floating point can produce tiny negatives
                sim = max(0.0, min(1.0, sim))
                rows.append([1.0 - sim, sim])
            except Exception:
                # Degenerate text (all stop-words, single char, etc.) → sim = 0
                rows.append([1.0, 0.0])
        return np.array(rows, dtype=float)

    # ── Run LIME ──────────────────────────────────────────────────────────────
    try:
        explainer = LimeTextExplainer(
            class_names=["no_match", "match"],
            random_state=42,    # fixed seed for reproducible explanations
        )
        explanation = explainer.explain_instance(
            text_instance=clean_resume,
            classifier_fn=_predict,
            labels=[1],         # explain the "match" class only
            num_features=num_features,
            num_samples=num_samples,
        )
        # as_list(label=1) → [(word, weight), ...]
        # Cast numpy str_ / float64 to plain Python types for JSON serialisation
        return {
            str(word): round(float(weight), 6)
            for word, weight in explanation.as_list(label=1)
        }

    except Exception as exc:
        logger.warning("explain_semantic_match failed: %s", exc)
        return {}
