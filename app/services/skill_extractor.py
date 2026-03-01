import json
from pathlib import Path

SKILLS_FILE = Path(__file__).resolve().parent.parent / "data" / "skills_master.json"

def extract_skills(resume_text: str):
    resume_text = resume_text.lower()
    extracted_skills = []

    with open(str(SKILLS_FILE), "r", encoding="utf-8") as f:
        skills = json.load(f)

    for skill in skills:
        if skill["name"].lower() in resume_text:
            extracted_skills.append({
                "skill_name": skill["name"],
                "skill_type": skill["type"]
            })

    return extracted_skills
