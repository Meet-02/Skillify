import re


ROLE_KEYWORDS = {
    "Data Scientist": ["machine learning", "data science", "pandas", "numpy", "statistics", "deep learning"],
    "Backend Developer": ["fastapi", "django", "flask", "api", "node", "backend"],
    "Frontend Developer": ["react", "javascript", "html", "css", "frontend"],
    "Full Stack Developer": ["react", "node", "full stack", "mongodb"],
    "AI Engineer": ["artificial intelligence", "deep learning", "nlp", "computer vision"],
}


def detect_role(resume_text: str, skills: list):

    text = resume_text.lower()
    skill_names = [s["skill_name"].lower() for s in skills]

    role_scores = {}

    for role, keywords in ROLE_KEYWORDS.items():
        score = 0

        for keyword in keywords:
            if keyword in text or keyword in skill_names:
                score += 1

        role_scores[role] = score

    # Pick highest scoring role
    best_role = max(role_scores, key=role_scores.get)

    # If no strong match
    if role_scores[best_role] == 0:
        return "Technology Professional"

    return best_role


def extract_experience_sentence(resume_text: str):

    lines = [l.strip() for l in resume_text.split("\n") if len(l.strip()) > 50]

    if lines:
        return lines[0][:180]

    return ""


def generate_advanced_bio(resume_text: str, skills: list):

    role = detect_role(resume_text, skills)

    top_skills = [s["skill_name"] for s in skills[:5]]

    skills_part = ", ".join(top_skills) if top_skills else "modern technologies"

    experience_part = extract_experience_sentence(resume_text)

    bio = (
        f"Aspiring {role} skilled in {skills_part}. "
    )

    if experience_part:
        bio += f"{experience_part}. "

    bio += "Passionate about building scalable, intelligent, and impactful solutions."

    return bio[:400]