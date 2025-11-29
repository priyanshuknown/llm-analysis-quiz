import os
import textwrap
import json
from typing import Any, Dict, List

import google.generativeai as genai
import asyncio

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")  # e.g. 'models/gemini-2.5-flash'

if not GEMINI_API_KEY:
    print("[WARN] GEMINI_API_KEY is not set. Gemini calls will fail.")
    model = None
else:
    genai.configure(api_key=GEMINI_API_KEY)
    if not GEMINI_MODEL:
        print("[ERROR] GEMINI_MODEL is not set. Set it to a valid model name from list_models().")
        model = None
    else:
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            print(f"[INFO] Using Gemini model: {GEMINI_MODEL}")
        except Exception as e:
            print(f"[ERROR] Could not initialize Gemini model '{GEMINI_MODEL}': {e}")
            model = None



async def ask_llm_for_answer(
    quiz_url: str,
    page_text: str,
    quiz_instructions: str,
    data_files: List[Dict[str, Any]],
) -> Any:
    """
    Ask Gemini to compute the 'answer' value for this quiz.

    Returns a Python object that can be JSON-serialized:
        - int / float / bool / str / dict / list
    """

    if model is None:
        raise RuntimeError("GEMINI_API_KEY or model is not configured correctly")

    # Prepare compact description of data files
    files_summary_parts = []
    for idx, f in enumerate(data_files, start=1):
        snippet = f.get("text_snippet", "")
        if len(snippet) > 4000:
            snippet = snippet[:4000] + "\n...[truncated]..."
        files_summary_parts.append(
            f"File {idx} ({f.get('url')}):\n"
            f"Content type: {f.get('content_type')}\n"
            f"Preview:\n{snippet}\n"
        )

    files_summary = "\n\n".join(files_summary_parts) if files_summary_parts else "No extra files."

    # Truncate page text to keep tokens reasonable
    if len(page_text) > 8000:
        page_text_short = page_text[:8000] + "\n...[truncated]..."
    else:
        page_text_short = page_text

    sys_prompt = textwrap.dedent(
        """
        You are an expert data-science quiz solver.
        You are given:
        - A QUIZ PAGE TEXT with instructions and examples.
        - Zero or more DATA FILES (CSV/JSON/TXT/PDF extracted as text).

        Your task: compute the exact value for the field named "answer" in a JSON payload
        we will send back to the quiz server.

        IMPORTANT RULES:
        - READ the instructions carefully.
        - Use only the information provided in the quiz text and data files.
        - If the answer is numeric, return just the number (no quotes).
        - If the answer is a boolean, return true or false (lowercase).
        - If the answer is a string, return the string without any extra commentary.
        - If the answer must be a JSON object or array, return valid JSON.
        - DO NOT include any explanation or extra text, only the final answer.
        """
    ).strip()

    user_prompt = textwrap.dedent(
        f"""
        QUIZ URL:
        {quiz_url}

        QUIZ PAGE TEXT:
        {page_text_short}

        QUIZ INSTRUCTIONS / QUESTION:
        {quiz_instructions}

        DATA FILES (if any, extracted as text):
        {files_summary}

        Now compute the required "answer" value.
        Output ONLY the final answer, nothing else.
        """
    ).strip()

    # Gemini client is synchronous; wrap in a thread so we can await it
    def _call_gemini():
        response = model.generate_content(
            [
                sys_prompt,
                "\n\n----\n\n",
                user_prompt,
            ]
        )
        return response.text.strip()

    raw_content = await asyncio.to_thread(_call_gemini)
    raw_content = raw_content.strip()

    # Try to interpret as JSON, number, boolean, or string

    # 1. Try JSON
    try:
        return json.loads(raw_content)
    except Exception:
        pass

    # 2. Boolean
    lowered = raw_content.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    # 3. Number
    try:
        if "." in raw_content:
            return float(raw_content)
        else:
            return int(raw_content)
    except Exception:
        pass

    # 4. Fallback: plain string
    return raw_content

