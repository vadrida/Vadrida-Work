import os
from google import genai
from django.conf import settings

def generate_gemini_summary(prompt_context):
    """
    Calls Gemini API to generate a summary based on provided context using the new google.genai SDK.
    """
    # Use GEMINI_API_KEY from .env, or fallback to GOOGLE_MAPS_API_KEY if applicable
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    
    if not api_key:
        return "Error: Gemini API Key not found in environment configuration."

    try:
        client = genai.Client(api_key=api_key)
        
        # Hardcoding the most stable, fastest flash model available in the current ecosystem
        model_name = 'gemini-2.5-flash'
        
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt_context,
            )
        except Exception:
            # Fallback to an older model if 2.5 is not available in the region
            model_name = 'gemini-1.5-flash'
            response = client.models.generate_content(
                model=model_name,
                contents=prompt_context,
            )
            
        return response.text.strip()
    except Exception as e:
        return f"Error with model {model_name if 'model_name' in locals() else 'gemini'}: {str(e)}"
