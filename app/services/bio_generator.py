import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def generate_bio(extracted_skills: list) -> str:
    """
    Generates a professional bio using Google Gemini AI.
    Handles 'extracted_skills' as a list of strings or dictionaries.
    """
    # 1. Extract skill names if the list contains dictionaries
    skills = []
    for item in extracted_skills:
        if isinstance(item, dict):
            skills.append(item.get('skill', ''))
        else:
            skills.append(str(item))
    
    # Remove empty strings
    skills = [s for s in skills if s.strip()]

    if not skills:
        return "A dedicated professional committed to continuous learning and growth."

    if not GEMINI_API_KEY:
        return f"Professional with expertise in: {', '.join(skills)}."

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        skills_str = ", ".join(skills)
        prompt = (
            f"Write a short, professional, and engaging 2-sentence professional bio "
            f"for a person with these skills: {skills_str}. "
            f"The tone should be modern. Do not use brackets or placeholders."
        )

        response = model.generate_content(prompt)
        
        if response and response.text:
            return response.text.strip()
        
    except Exception as e:
        print(f"Gemini API Error: {e}")
    
    return f"Experienced professional specialized in {', '.join(skills)}."