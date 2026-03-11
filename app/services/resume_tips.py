"""
Resume Enhancement Tips Service
Uses Hugging Face Inference API (free tier) to generate resume improvement tips
after a successful resume upload or profile creation.

NOTE ON PRICING:
- Hugging Face Inference API has a FREE tier with rate limits.
- For light usage (dev/testing), it is FREE.
- For production/heavy usage, you need a HF Pro account ($9/month).
- The model used here (mistralai/Mistral-7B-Instruct-v0.2) is a public model
  accessible on the free tier with usage caps.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

HF_API_KEY = os.getenv("HF_API_KEY")

# Using a free, publicly available instruction-tuned model on HF
# You can swap this with any other text-generation model on HF Hub
HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"
HF_API_URL = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}"


def generate_resume_tips(skills: list, profile: dict = None) -> list[str]:
    """
    Calls HuggingFace Inference API to generate resume enhancement tips.

    Args:
        skills: List of skill dicts [{"skill_name": ..., "skill_type": ...}]
        profile: Optional profile dict with keys like experience_level, domain_interest

    Returns:
        List of tip strings, or fallback tips if API call fails.
    """

    # Build skill names list
    skill_names = []
    for s in skills:
        if isinstance(s, dict):
            name = s.get("skill_name") or s.get("skill") or ""
        else:
            name = str(s)
        if name.strip():
            skill_names.append(name.strip())

    if not skill_names:
        return _fallback_tips()

    # Build context from profile if available
    experience = "unknown"
    domain = "general"
    if profile:
        experience = profile.get("experience_level") or "unknown"
        domain = profile.get("domain_interest") or "general"

    skills_str = ", ".join(skill_names[:20])  # limit to 20 skills

    prompt = f"""<s>[INST] You are a professional resume coach. A user has uploaded their resume with the following skills: {skills_str}.
Their experience level is: {experience}. Their domain of interest is: {domain}.

Give exactly 5 short, specific, and actionable tips to help them improve their resume and profile. 
Format your response as a numbered list only (1. ... 2. ... etc.), no extra explanation. [/INST]"""

    if not HF_API_KEY:
        print("⚠️  HF_API_KEY not set — returning fallback tips")
        return _fallback_tips(skill_names)

    try:
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 400,
                "temperature": 0.7,
                "return_full_text": False,
            },
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(HF_API_URL, headers=headers, json=payload)

        if response.status_code == 200:
            result = response.json()
            generated_text = ""
            if isinstance(result, list) and result:
                generated_text = result[0].get("generated_text", "")
            elif isinstance(result, dict):
                generated_text = result.get("generated_text", "")

            tips = _parse_numbered_tips(generated_text)
            if tips:
                return tips

        elif response.status_code == 503:
            # Model is loading (cold start) — this is common on free tier
            print("⚠️  HF model is loading (503). Returning fallback tips.")
        elif response.status_code == 429:
            print("⚠️  HF rate limit hit (429). Returning fallback tips.")
        else:
            print(f"⚠️  HF API error {response.status_code}: {response.text}")

    except Exception as e:
        print(f"⚠️  HF API exception: {e}")

    return _fallback_tips(skill_names)


def _parse_numbered_tips(text: str) -> list[str]:
    """Extract numbered tips (1. ... 2. ...) from generated text."""
    import re
    lines = text.strip().split("\n")
    tips = []
    for line in lines:
        line = line.strip()
        if re.match(r"^\d+[\.\)]\s+.{10,}", line):
            # Remove the number prefix for clean display
            clean = re.sub(r"^\d+[\.\)]\s+", "", line).strip()
            tips.append(clean)
    return tips[:5]  # Return max 5 tips


def _fallback_tips(skills: list = None) -> list[str]:
    """Returns generic fallback tips when API is unavailable."""
    tips = [
        "Add quantifiable achievements to each work experience (e.g., 'Improved performance by 30%').",
        "Include a concise professional summary at the top of your resume tailored to your target role.",
        "List certifications and online courses relevant to your skill set to strengthen credibility.",
        "Use strong action verbs (built, designed, automated, led) to describe your experience.",
        "Ensure your LinkedIn profile matches your resume and is kept up to date.",
    ]
    if skills:
        popular = ["Python", "React", "AWS", "Docker", "SQL", "Machine Learning"]
        missing = [s for s in popular if s not in skills]
        if missing:
            tips[2] = f"Consider learning in-demand skills like {', '.join(missing[:3])} to boost your profile."
    return tips
