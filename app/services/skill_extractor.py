import json
import re
from pathlib import Path

SKILLS_FILE = Path(__file__).resolve().parent.parent / "data" / "skills_master.json"

_skills_cache = None


def _load_skills():
    global _skills_cache
    if _skills_cache is None:
        with open(str(SKILLS_FILE), "r", encoding="utf-8") as f:
            _skills_cache = json.load(f)
    return _skills_cache


def _word_in_text(word: str, text: str) -> bool:
    """Match whole-word or phrase in text to avoid false positives (e.g. 'R' matching 'React')."""
    # For very short tokens (1-2 chars), require word boundaries
    pattern = r"(?<![a-zA-Z0-9_+#])" + re.escape(word) + r"(?![a-zA-Z0-9_+#])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def extract_skills(resume_text: str):
    """
    Extract skills from resume text using canonical names and synonyms.

    Returns a list of dicts:
      {
        "skill_name": str,
        "skill_type": str,       # "technical" | "soft" | "domain" | "language"
        "category":   str,       # e.g. "Programming Languages", "Cloud"
        "roles":      list[str]  # associated job roles
      }
    """
    skills = _load_skills()
    extracted = []
    seen = set()

    for skill in skills:
        skill_name = skill["name"]
        if skill_name in seen:
            continue

        matched = _word_in_text(skill_name, resume_text)

        if not matched:
            for synonym in skill.get("synonyms", []):
                if _word_in_text(synonym, resume_text):
                    matched = True
                    break

        if matched:
            seen.add(skill_name)
            extracted.append({
                "skill_name": skill_name,
                "skill_type": skill.get("type", "technical"),
                "category":   skill.get("category", ""),
                "roles":      skill.get("roles", []),
            })

    return extracted


def get_skills_by_role(role: str):
    """Return all skills associated with a given job role."""
    skills = _load_skills()
    role_lower = role.lower()
    return [
        s for s in skills
        if any(r.lower() == role_lower for r in s.get("roles", []))
    ]


def get_skills_by_category(category: str):
    """Return all skills in a given category."""
    skills = _load_skills()
    return [
        s for s in skills
        if s.get("category", "").lower() == category.lower()
    ]


def get_all_categories():
    """Return a sorted list of all unique skill categories."""
    skills = _load_skills()
    return sorted({s.get("category", "") for s in skills if s.get("category")})


def get_all_roles():
    """Return a sorted list of all unique job roles."""
    skills = _load_skills()
    roles = set()
    for s in skills:
        roles.update(s.get("roles", []))
    return sorted(roles)
