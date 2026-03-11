from google import genai
from google.genai import types # Added for advanced config
import os
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the Client with specific API version options
client = None
if GEMINI_API_KEY:
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={'api_version': 'v1beta'} # Explicitly set version
    )

def generate_bio(extracted_skills: list) -> str:
    """
    Generates a professional bio using the NEW Google GenAI SDK.
    """
    # Clean and extract skill names
    skills = []
    for item in extracted_skills:
        if isinstance(item, dict):
            name = item.get('skill_name') or item.get('skill')
            if name: skills.append(name)
        else:
            skills.append(str(item))
    
    skills = [s for s in skills if s.strip()]

    if not skills:
        return "A dedicated professional committed to continuous learning and growth."

    if not client:
        return f"Professional with expertise in: {', '.join(skills)}."

    try:
        skills_str = ", ".join(skills)
        prompt = f"""
        Write a professional LinkedIn-style bio in 2 sentences.

        Skills: {skills_str}

        Make the person sound ambitious and career-oriented.
        Avoid generic phrases like "dedicated professional".
        """

        # Try using the specific model ID
        response = client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt
        )
        
        if response and response.text:
            return response.text.strip()
        
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # If gemini-1.5-flash fails again, try the older naming convention as a backup
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=prompt
            )
            return response.text.strip()
        except:
            pass
    
    return f"Experienced professional specialized in {', '.join(skills)}."