# quiz_solver.py
import json
from typing import Any, Dict

import requests
from playwright.sync_api import sync_playwright
from openai import OpenAI

from config import OPENAI_API_KEY


# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


def load_quiz_page(quiz_url: str) -> dict:
    """
    Load quiz page in a headless Chromium browser so that
    JavaScript runs and DOM is fully rendered.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Wait for network idle, in case the quiz fetches extra data
        page.goto(quiz_url, wait_until="networkidle", timeout=120_000)
        body_text = page.inner_text("body")
        full_html = page.content()
        browser.close()

    return {"text": body_text, "html": full_html}


def ask_llm_for_plan(
    quiz_url: str,
    email: str,
    secret: str,
    quiz_page: dict,
    original_payload: dict,
) -> Dict[str, Any]:
    """
    Use OpenAI to:
    - Understand quiz instructions
    - Identify submit URL
    - Build JSON payload to send to submit URL

    We force a JSON response using response_format={"type": "json_object"}.
    """

    system_message = (
        "You are a careful assistant that solves data quizzes and returns JSON only. "
        "You must read the quiz page, understand the instructions, and build a JSON "
        "object describing how to submit the answer."
    )

    user_instructions = """
You are given:
1. The URL where the quiz page is hosted.
2. The rendered text and HTML of the page.
3. The student's email and secret (used for authentication).

TASK:

1. Read the quiz instructions in the page.
2. Identify the exact URL where the answer must be submitted (submit_url).
   - This is often written like: "Post your answer to https://example.com/submit".
3. Figure out what the "answer" should be conceptually.
   - Do NOT download files yourself in this step; just reason about what needs to be done.
   - The surrounding Python code will handle downloads/computations where needed.
4. Build the JSON payload that must be sent to the submit URL.
   - Always include: "email", "secret", and "url" (the original quiz URL).
   - Add an "answer" field (or whatever the quiz demands) with the correct type:
       * number / string / boolean / base64 URI / nested JSON, etc.
   - Keep payload size under 1MB.

Return JSON in this exact schema:

{
  "reasoning_summary": "short explanation of what the quiz asked and how you solved it",
  "submit_url": "https://....",
  "answer_payload": {
      "email": "...",
      "secret": "...",
      "url": "https://quiz-url",
      "answer": <value or object as required by the quiz>
      // you may add more keys if quiz requires them
  }
}

IMPORTANT RULES:
- Output MUST be valid JSON.
- Do NOT include comments or trailing commas.
- Do NOT add extra top-level keys.
"""

    # Context object with quiz details
    user_content = {
        "quiz_url": quiz_url,
        "student_email": email,
        "student_secret": secret,
        "original_payload": original_payload,
        "quiz_page_text": quiz_page["text"],
        "quiz_page_html": quiz_page["html"],
    }

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_instructions,
                    },
                    {
                        "type": "text",
                        "text": json.dumps(user_content)[:30000],  # safety limit
                    },
                ],
            },
        ],
    )

    content = response.choices[0].message.content
    plan = json.loads(content)
    return plan


def submit_answer(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send answer_payload to submit_url.
    Return JSON from submit endpoint plus what was sent.
    """
    submit_url = plan["submit_url"]
    answer_payload = plan["answer_payload"]

    if not isinstance(submit_url, str) or not submit_url.startswith("http"):
        raise ValueError(f"submit_url looks invalid: {submit_url}")

    resp = requests.post(submit_url, json=answer_payload, timeout=120)
    resp.raise_for_status()

    try:
        resp_json = resp.json()
    except Exception:
        resp_json = {"raw_text": resp.text}

    return {
        "submit_url": submit_url,
        "answer_payload": answer_payload,
        "quiz_response": resp_json,
    }


def solve_quiz(
    quiz_url: str,
    incoming_payload: dict,
    email: str,
    secret: str,
) -> Dict[str, Any]:
    """
    High-level orchestration:

    1. Load quiz page via Playwright (JS executes).
    2. Ask LLM to understand instructions and build a plan.
    3. Submit the answer to the instructed submit URL.
    4. Return final JSON that will be sent back to TDS evaluator.
    """
    quiz_page = load_quiz_page(quiz_url)

    plan = ask_llm_for_plan(
        quiz_url=quiz_url,
        email=email,
        secret=secret,
        quiz_page=quiz_page,
        original_payload=incoming_payload,
    )

    submission_result = submit_answer(plan)

    return {
        "quiz_url": quiz_url,
        "llm_reasoning_summary": plan.get("reasoning_summary"),
        "submit_url": submission_result["submit_url"],
        "answer_payload": submission_result["answer_payload"],
        "quiz_response": submission_result["quiz_response"],
    }
