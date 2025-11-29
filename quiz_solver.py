# quiz_solver.py
import asyncio
import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
from pypdf import PdfReader
from playwright.async_api import async_playwright

from grok_client import ask_grok_for_answer

HTTP_TIMEOUT = 60  # seconds


async def fetch_quiz_page(url: str) -> Tuple[str, str, List[str]]:
    """
    Use Playwright to render the quiz page (JS-enabled).
    Returns: (html, visible_text, list_of_links)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=HTTP_TIMEOUT * 1000)

        html = await page.content()
        # Visible text
        try:
            text = await page.inner_text("body")
        except Exception:
            text = html

        # Collect all href links
        links = await page.eval_on_selector_all(
            "a",
            "els => els.map(e => e.href)"
        )

        await browser.close()

    return html, text, links


def extract_quiz_instructions(page_text: str) -> str:
    """
    Heuristic: the question usually appears after something like 'Qxxx.' or 'Question'.
    For now, we just return the full text; Grok will pick the relevant part.
    """
    return page_text


def find_submit_url(page_text: str, links: List[str]) -> Optional[str]:
    """
    Try to find the submit URL from page text or links.
    Typically it looks like: 'Post your answer to https://example.com/submit ...'.
    """
    # 1. Look for 'Post your answer to <url>'
    m = re.search(r"Post your answer to\s+(https?://[^\s\"']+)", page_text)
    if m:
        return m.group(1).strip()

    # 2. Fallback: any link containing 'submit'
    for link in links:
        if "submit" in link:
            return link

    return None


async def download_and_extract_file_text(url: str) -> Dict[str, Any]:
    """
    Download file and convert to text summary for Grok.
    Supports CSV, JSON, TXT, PDF (basic text extraction).
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        raw = r.content

    text_snippet = ""
    if url.lower().endswith(".csv") or "text/csv" in content_type:
        df = pd.read_csv(pd.io.common.BytesIO(raw))
        text_snippet = df.to_csv(index=False)
    elif url.lower().endswith(".json") or "application/json" in content_type:
        try:
            obj = json.loads(raw)
            text_snippet = json.dumps(obj, indent=2)
        except Exception:
            text_snippet = raw.decode("utf-8", errors="ignore")
    elif url.lower().endswith(".pdf") or "application/pdf" in content_type:
        reader = PdfReader(pd.io.common.BytesIO(raw))
        pages_text = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                pages_text.append(f"[Page {i}]\n" + page.extract_text())
            except Exception:
                continue
        text_snippet = "\n\n".join(pages_text)
    else:
        # Treat as generic text
        text_snippet = raw.decode("utf-8", errors="ignore")

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
    - Render page
    - Extract instructions & submit URL
    - Download data files
    - Ask Grok for 'answer'
    - Submit to quiz server
    Returns dict with details, including any next URL.
    """
    html, page_text, links = await fetch_quiz_page(quiz_url)
    instructions = extract_quiz_instructions(page_text)
    submit_url = find_submit_url(page_text, links)

    if not submit_url:
        raise RuntimeError(f"Could not find submit URL on quiz page: {quiz_url}")

    data_files = await discover_data_files(links)

    # Ask Grok for answer, using all context
    answer = await ask_grok_for_answer(
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
