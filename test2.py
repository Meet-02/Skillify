from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

try:
    # Most direct call possible
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite", # Or "gemini-1.5-flash"
        contents="Say 'The API is working correctly'"
    )
    print(response.text)
except Exception as e:
    print(f"Error: {e}")