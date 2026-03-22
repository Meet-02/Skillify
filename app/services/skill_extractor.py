
import json
import re
from pathlib import Path
 
SKILLS_FILE = Path(__file__).resolve().parent.parent / "data" / "skills_master.json"
 
# Each entry: (canonical_name, skill_type, category, roles, compiled_pattern)
_compiled_skills: list = []
_cache_built = False
 
 
def _boundary(token: str) -> str:
    """Wrap token in word-boundary lookarounds."""
    return r"(?<![a-zA-Z0-9_+#])" + re.escape(token) + r"(?![a-zA-Z0-9_+#])"
 
 
def _build_cache() -> None:
    global _compiled_skills, _cache_built
    if _cache_built:
        return
 
    with open(str(SKILLS_FILE), "r", encoding="utf-8") as f:
        raw = json.load(f)
 
    compiled = []
    seen_names: set = set()
 
    for skill in raw:
        name = skill.get("name", "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
 
        tokens = [name] + [s.strip() for s in skill.get("synonyms", []) if s.strip()]
        alternation = "|".join(_boundary(t) for t in tokens)
        try:
            pattern = re.compile("(?:" + alternation + ")", re.IGNORECASE)
        except re.error:
            pattern = re.compile(_boundary(name), re.IGNORECASE)
 
        compiled.append((
            name,
            skill.get("type", "technical"),
            skill.get("category", ""),
            skill.get("roles", []),
            pattern,
        ))
 
    _compiled_skills = compiled
    _cache_built = True
 
 
# Build at import time — first request pays no extra cost
_build_cache()
 
 
def extract_skills(text: str) -> list:
    """
    Extract skills from text using pre-compiled patterns.
    Returns list of dicts: { skill_name, skill_type, category, roles }
    """
    if not _cache_built:
        _build_cache()
 
    extracted = []
    seen: set = set()
 
    for name, skill_type, category, roles, pattern in _compiled_skills:
        if name in seen:
            continue
        if pattern.search(text):
            seen.add(name)
            extracted.append({
                "skill_name": name,
                "skill_type": skill_type,
                "category":   category,
                "roles":      roles,
            })
 
    return extracted
 
 
def get_skills_by_role(role: str) -> list:
    if not _cache_built:
        _build_cache()
    role_lower = role.lower()
    return [
        {"name": n, "type": t, "category": c, "roles": r}
        for n, t, c, r, _ in _compiled_skills
        if any(x.lower() == role_lower for x in r)
    ]
 
 
def get_skills_by_category(category: str) -> list:
    if not _cache_built:
        _build_cache()
    cat_lower = category.lower()
    return [
        {"name": n, "type": t, "category": c, "roles": r}
        for n, t, c, r, _ in _compiled_skills
        if c.lower() == cat_lower
    ]
 
 
def get_all_categories() -> list:
    if not _cache_built:
        _build_cache()
    return sorted({c for _, _, c, _, _ in _compiled_skills if c})
 
 
def get_all_roles() -> list:
    if not _cache_built:
        _build_cache()
    roles: set = set()
    for _, _, _, r, _ in _compiled_skills:
        roles.update(r)
    return sorted(roles)
 