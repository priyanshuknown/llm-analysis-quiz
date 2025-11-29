# quiz_solver.py
import asyncio
import os
import re
import json
import io
import base64
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
from urllib.parse import urljoin

from gemini_client import ask_llm_for_answer

HTTP_TIMEOUT = 60  # seconds


async def fetch_quiz_page(url: str) -> Tuple[str, str, List[str]]:
    """
    Fetch the quiz page using plain HTTP (no JS execution).
    Additionally:
    - Detect any atob(`...`) or atob("...") calls in <script> tags.
    - Base64-decode those strings to reconstruct the rendered HTML/text.
    - Return:
        html          = original HTML
        page_text     = plain text from HTML + decoded segments
        links         = all href links from original HTML + decoded segments
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text

    # --- 1. Decode base64 segments from atob() calls ---

    decoded_segments: List[str] = []

    # Pattern: atob(`....`)
    for m in re.finditer(r"atob\(\s*`([^`]+)`\s*\)", html, flags=re.DOTALL):
        b64 = m.group(1).replace("\n", "").replace("\r", "")
        try:
            decoded = base64.b64decode(b64).decode("utf-8", errors="ignore")
            decoded_segments.append(decoded)
        except Exception:
            continue

    # Pattern: atob("....")
    for m in re.finditer(r'atob\(\s*"([^"]+)"\s*\)', html, flags=re.DOTALL):
        b64 = m.group(1).replace("\n", "").replace("\r", "")
        try:
            decoded = base64.b64decode(b64).decode("utf-8", errors="ignore")
            decoded_segments.append(decoded)
        except Exception:
            continue

    # --- 2. Plain-text extraction from original HTML (without scripts/styles) ---

    no_script_html = re.sub(
        r"<script.*?>.*?</script>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    no_style_html = re.sub(
        r"<style.*?>.*?</style>",
        " ",
        no_script_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    plain_html_text = re.sub(r"<[^>]+>", " ", no_style_html)
    plain_html_text = re.sub(r"\s+", " ", plain_html_text).strip()

    # --- 3. Extract links from original HTML ---

    raw_links = re.findall(r'href=["\']([^"\']+)["\']', html)
    links = [urljoin(url, link) for link in raw_links]

    # --- 4. Extract links from decoded segments (they usually contain <a href="...">) ---

    for seg in decoded_segments:
        for link in re.findall(r'href=["\']([^"\']+)["\']', seg):
            links.append(urljoin(url, link))

    # Deduplicate links
    links = list(dict.fromkeys(links))

    # --- 5. Combine plain HTML text with decoded segments as page_text ---

    decoded_text = "\n\n".join(
        re.sub(r"\s+", " ", seg).strip() for seg in decoded_segments
    )

    if decoded_text:
        page_text = plain_html_text + "\n\n" + decoded_text
    else:
        page_text = plain_html_text

    return html, page_text, links


def extract_quiz_instructions(page_text: str) -> str:
    """
    For now, just return the full page_text.
    Gemini will focus on the relevant question/instructions.
    """
    return page_text


def find_submit_url(page_text: str, links: List[str]) -> Optional[str]:
    """
    Try to find the submit URL from:
    - Text like: 'Post your answer to https://example.com/submit ...'
    - Any URL in text containing 'submit'
    - Any href link containing 'submit'
    """
    # 1. Exact pattern: 'Post your answer to <url>'
    m = re.search(r"Post your answer to\s+(https?://[^\s\"'<>]+)", page_text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 2. Any URL in the text that contains 'submit'
    m = re.search(r"(https?://[^\s\"'<>]*submit[^\s\"'<>]*)", page_text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 3. Fallback: any link from hrefs that contains 'submit'
    for link in links:
        if "submit" in link.lower():
            return link

    return None


async def download_and_extract_file_text(url: str) -> Dict[str, Any]:
    """
    Download file and convert to text summary for the LLM.

    To avoid NotImplementedError / PDF issues, we **do not** try to parse PDFs.
    - CSV → read with pandas
    - JSON → pretty-print or raw text
    - TXT/other → raw text
    - PDF → just a placeholder message

    This function must **never raise**; on any error it returns a short error message.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        raw = r.content

    text_snippet = ""
    try:
        lower_url = url.lower()

        # CSV
        if lower_url.endswith(".csv") or "text/csv" in content_type:
            df = pd.read_csv(io.BytesIO(raw))
            text_snippet = df.to_csv(index=False)

        # JSON
        elif lower_url.endswith(".json") or "application/json" in content_type:
            try:
                obj = json.loads(raw)
                text_snippet = json.dumps(obj, indent=2)
            except Exception:
                text_snippet = raw.decode("utf-8", errors="ignore")

        # PDF → DO NOT PARSE, just mark it
        elif lower_url.endswith(".pdf") or "application/pdf" in content_type:
            text_snippet = "[PDF file linked here; PDF parsing disabled to avoid NotImplementedError.]"

        # Generic text / others
        else:
            text_snippet = raw.decode("utf-8", errors="ignore")

    except Exception as e:
        text_snippet = f"[Error while parsing file: {type(e).__name__}]"

    return {
        "url": url,
        "content_type": content_type,
        "text_snippet": text_snippet,
    }


async def discover_data_files(links: List[str]) -> List[Dict[str, Any]]:
    """
    From all page links, pick those that look like data files (csv/json/pdf/txt)
    and download them.
    """
    data_links = [
        link for link in links
        if any(
            link.lower().endswith(ext)
            for ext in (".csv", ".json", ".txt", ".pdf")
        )
    ]

    tasks = [download_and_extract_file_text(l) for l in data_links]
    if not tasks:
        return []

    return await asyncio.gather(*tasks)


async def solve_single_quiz(
    quiz_url: str,
    student_email: str,
    student_secret: str,
) -> Dict[str, Any]:
    """
    Solve one quiz URL:
    - Render page (via HTTP + base64 decoding)
    - Extract instructions & submit URL
    - Download data files
    - Ask Gemini for 'answer'
    - Submit to quiz server
    Returns dict with details, including any next URL.
    """
    html, page_text, links = await fetch_quiz_page(quiz_url)
    instructions = extract_quiz_instructions(page_text)
    submit_url = find_submit_url(page_text, links)

    if not submit_url:
        raise RuntimeError(f"Could not find submit URL on quiz page: {quiz_url}")

    data_files = await discover_data_files(links)

    # Ask Gemini for answer, using all context
    answer = await ask_llm_for_answer(
        quiz_url=quiz_url,
        page_text=page_text,
        quiz_instructions=instructions,
        data_files=data_files,
    )

    # Build payload to submit
    submit_payload = {
        "email": student_email,
        "secret": student_secret,
        "url": quiz_url,
        "answer": answer,
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(submit_url, json=submit_payload)
        resp.raise_for_status()
        resp_json = resp.json()

    # Next URL if any
    next_url = resp_json.get("url")

    return {
        "quiz_url": quiz_url,
        "submit_url": submit_url,
        "answer": answer,
        "submit_response": resp_json,
        "next_url": next_url,
    }


async def run_quiz_chain(
    start_url: str,
    student_email: str,
    student_secret: str,
    max_steps: int = 5,
) -> Dict[str, Any]:
    """
    Repeatedly solve quizzes starting from start_url
    until there's no new url or we hit max_steps.
    """
    results: List[Dict[str, Any]] = []
    current_url = start_url

    for step in range(1, max_steps + 1):
        step_result = await solve_single_quiz(
            quiz_url=current_url,
            student_email=student_email,
            student_secret=student_secret,
        )
        results.append(step_result)

        next_url = step_result.get("next_url")
        if not next_url:
            break
        current_url = next_url

    return {
        "start_url": start_url,
        "steps_taken": len(results),
        "results": results,
    }
