from google import genai
import os
import time
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
    Includes retry logic for 429 rate-limit errors.
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

    skills_str = ", ".join(skills)
    prompt = f"""
    Write a professional LinkedIn-style bio in 2 sentences.

    Skills: {skills_str}

    Make the person sound ambitious and career-oriented.
    Avoid generic phrases like "dedicated professional".
    """

    # Retry with exponential backoff for 429 rate-limit errors
    max_retries = 3
    wait_time = 40  # seconds (API suggested ~37s)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-1.5-flash", 
                contents=prompt
            )
            
            if response and response.text:
                return response.text.strip()
            break  # Successful but empty — don't retry
            
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    print(f"Gemini API rate limited (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    wait_time *= 2  # Exponential backoff
                else:
                    print(f"Gemini API rate limited after {max_retries} attempts. Using fallback.")
            else:
                print(f"Gemini API Error: {e}")
                # Try backup model once
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-lite",
                        contents=prompt
                    )
                    if response and response.text:
                        return response.text.strip()
                except Exception:
                    pass
                break  # Non-retryable error
    
    return f"Experienced professional specialized in {', '.join(skills)}."