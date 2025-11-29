# grok_client.py
import os
import textwrap
import json
from typing import Any, Dict, List, Optional

from xai_sdk import AsyncClient
from xai_sdk.chat import system, user

XAI_API_KEY = os.getenv("XAI_API_KEY")

if not XAI_API_KEY:
    # FastAPI will still start, but we'll clearly crash on first Grok call if not set.
    print("[WARN] XAI_API_KEY is not set. Grok calls will fail.")

# Single global async client
grok_client = AsyncClient(api_key=XAI_API_KEY, timeout=180)


async def ask_grok_for_answer(
    quiz_url: str,
    page_text: str,
    quiz_instructions: str,
    data_files: List[Dict[str, Any]],
) -> Any:
    """
    Ask Grok to compute the 'answer' value for this quiz.

    Returns a Python object that can be JSON-serialized:
        - int / float / bool / str / dict / list
    """

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

    chat = grok_client.chat.create(
        model="grok-4",  # you can change to grok-4-fast or grok-3-mini to save cost
        messages=[
            system(sys_prompt),
            user(user_prompt),
        ],
    )

    response = await chat.sample()
    raw_content = str(response.content).strip()

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
