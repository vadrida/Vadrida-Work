import os
import google.generativeai as genai
from django.conf import settings

def generate_gemini_summary(prompt_context):
    """
    Calls Gemini API to generate a summary based on provided context.
    """
    # Use GEMINI_API_KEY from .env, or fallback to GOOGLE_MAPS_API_KEY if applicable
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    
    if not api_key:
        return "Error: Gemini API Key not found in environment configuration."

    try:
        genai.configure(api_key=api_key)
        
        # Dynamically find the best available flash model to avoid version mismatches
        # In 2026, models like gemini-2.0-flash or gemini-3.0-flash might be standard
        model_name = 'gemini-1.5-flash'  # Fallback
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # Prioritize stable flash models, avoid specialized/preview models
            # We must exclude 'image', 'vision', 'tts', 'audio', 'embedding' as they might return non-text parts
            excluded_terms = ['preview', 'exp', 'image', 'vision', 'tts', 'audio', 'embedding', 'audit']
            
            stable_flash = [m for m in available_models if 'flash' in m.lower() and not any(term in m.lower() for term in excluded_terms)]
            all_flash = [m for m in available_models if 'flash' in m.lower() and not any(term in m.lower() for term in ['image', 'vision', 'tts'])]
            
            if stable_flash:
                model_name = stable_flash[-1]
            elif all_flash:
                model_name = all_flash[-1]
            elif available_models:
                model_name = available_models[0]
        except Exception as list_err:
            print(f"Model list failed: {list_err}")

        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt_context)
        return response.text.strip()
    except Exception as e:
        return f"Error with model {model_name}: {str(e)}"
