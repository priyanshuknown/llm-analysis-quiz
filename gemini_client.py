import os
import textwrap
import json
from typing import Any, Dict, List

import google.generativeai as genai
import asyncio

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("[WARN] GEMINI_API_KEY is not set. Gemini calls will fail.")
    model = None
else:
    genai.configure(api_key=GEMINI_API_KEY)
    # Use a stable, widely supported model
    MODEL_NAME = "gemini-pro"
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        print(f"[INFO] Using Gemini model: {MODEL_NAME}")
    except Exception as e:
        print(f"[ERROR] Could not initialize Gemini model '{MODEL_NAME}': {e}")
        model = None
