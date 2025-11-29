# quiz_solver.py

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from gemini_client import ask_llm_for_answer

# Global HTTP client timeout (in seconds)
HTTP_TIMEOUT = 60.0


# ---------------------------------------------------------
# 1. Fetch and parse quiz page
# ---------------------------------------------------------

async def fetch_quiz_page(url: str) -> Tuple[str, str, List[str]]:
    """
    Fetch the quiz page HTML and extract:
      - raw HTML
      - text content (including decoded atob(`...`) blocks)
      - list of links (href URLs)
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http_client:
        resp = await http_client.get(url)
        resp.raise_for_status()
        html = resp.text

    # Basic text extraction: strip tags roughly
    page_text = strip_html_tags(html)

    # Handle atob(`...`) JavaScript blocks that contain base64 text of the question
    decoded_texts = extract_atob_blocks(html)
    if decoded_texts:
        page_text += "\n\n" + "\n\n".join(decoded_texts)

    # Extract all links
    links = extract_links(html)
    # Also try to capture http/https URLs that appear as plain text
    links.extend(extract_inline_urls(page_text))

    # Deduplicate links
    links = sorted(set(links))

    return html, page_text, links


def strip_html_tags(html: str) -> str:
    """Very rough HTML → text conversion."""
    # Remove script and style
    html = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Replace <br> and <p> with newlines
    html = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p\s*>", "\n", html, flags=re.IGNORECASE)

    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", html)
    # Unescape common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    return text


def extract_links(html: str) -> List[str]:
    """Extract href links from <a href="..."> tags."""
    links: List[str] = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        links.append(m.group(1))
    return links


def extract_inline_urls(text: str) -> List[str]:
    """Extract http/https URLs that appear as plain text in the page."""
    urls: List[str] = []
    for m in re.finditer(r"https?://[^\s\"'<>]+", text):
        urls.append(m.group(0))
    return urls


def extract_atob_blocks(html: str) -> List[str]:
    """
    Look for JS blocks like:
      atob(`...base64...`)
    Decode them as UTF-8 and return the decoded strings.
    """
    decoded: List[str] = []
    for m in re.finditer(r"atob\(\s*`([^`]+)`\s*\)", html):
        b64 = m.group(1).strip()
        try:
            import base64

            data = base64.b64decode(b64)
            decoded_text = data.decode("utf-8", errors="replace")
            decoded.append(decoded_text)
        except Exception:
            # Ignore malformed base64
            continue
    return decoded


# ---------------------------------------------------------
# 2. Extract quiz instructions and submit / payload info
# ---------------------------------------------------------

def extract_quiz_instructions(page_text: str) -> str:
    """
    For now, use the entire page text as instructions.

    You could get fancier (e.g., look for lines starting with 'Qxxx.'), but this
    is usually enough for the LLM to understand the question.
    """
    return page_text.strip()


def extract_submission_template(page_text: str) -> Optional[Dict[str, Any]]:
    """
    Try to extract a JSON payload template from the quiz page.

    Many quizzes show something like:

      Post your answer to https://.../submit with this JSON payload:

      <pre>
      {
        "email": "your email",
        "secret": "your secret",
        "url": "https://example.com/quiz-834",
        "answer": 12345  // the correct answer
      }
      </pre>

    We'll:
      - find a '{ ... }' block that mentions "email" and "secret"
      - strip // comments
      - parse as JSON
    """
    if not page_text:
        return None

    match = re.search(
        r"\{[^{}]*\"email\"[^{}]*\"secret\"[^{}]*\}",
        page_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None

    raw_block = match.group(0)

    # Remove // comments
    cleaned_lines: List[str] = []
    for line in raw_block.splitlines():
        line = line.split("//", 1)[0]
        if line.strip():
            cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # Remove trailing commas before '}' or ']'
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)

    try:
        template = json.loads(cleaned)
        if isinstance(template, dict):
            return template
    except Exception:
        return None

    return None


def find_submit_url(
    quiz_url: str,
    page_text: str,
    links: List[str],
    html: str,
) -> Optional[str]:
    """
    Try to find the submit URL from:
      - Text like: 'Post your answer to https://example.com/submit ...'
      - Any absolute URL in text containing 'submit'
      - Any relative '/submit...' in text or HTML
      - Any href link containing 'submit'
    """
    blob = (page_text or "") + "\n" + (html or "")

    # 1. Exact phrase: 'Post your answer to <url>'
    m = re.search(
        r"Post your answer to\s+(https?://[^\s\"'<>]+)",
        blob,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # 2. Any absolute URL containing 'submit'
    m = re.search(
        r"(https?://[^\s\"'<>]*submit[^\s\"'<>]*)",
        blob,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # 3. Any relative '/submit...' pattern
    m = re.search(
        r"(/submit[^\s\"'<>]*)",
        blob,
        flags=re.IGNORECASE,
    )
    if m:
        return urljoin(quiz_url, m.group(1).strip())

    # 4. Fallback: any href link we collected that contains 'submit'
    for link in links:
        if "submit" in link.lower():
            # Make relative URLs absolute
            return urljoin(quiz_url, link)

    return None


# ---------------------------------------------------------
# 3. Data file downloading / extraction
# ---------------------------------------------------------

async def download_and_extract_file_text(url: str) -> str:
    """
    Download a data file (CSV, JSON, TXT, PDF, etc) and return a text summary.

    We do very lightweight parsing:
      - CSV / TSV: load into text
      - JSON: pretty-print
      - TXT: raw text
      - PDF: try to extract text with pypdf if available, else note it's a PDF
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http_client:
        resp = await http_client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        data = resp.content

    text_summary = ""

    # Decide based on content type or file extension
    lowered = content_type.lower()
    if "text/csv" in lowered or url.lower().endswith(".csv"):
        text_summary = data.decode("utf-8", errors="replace")
    elif "application/json" in lowered or url.lower().endswith(".json"):
        try:
            obj = json.loads(data.decode("utf-8", errors="replace"))
            text_summary = json.dumps(obj, indent=2)[:8000]
        except Exception:
            text_summary = data.decode("utf-8", errors="replace")
    elif "text/plain" in lowered or url.lower().endswith(".txt"):
        text_summary = data.decode("utf-8", errors="replace")
    elif "pdf" in lowered or url.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore

            import io

            reader = PdfReader(io.BytesIO(data))
            chunks: List[str] = []
            for page in reader.pages:
                chunks.append(page.extract_text() or "")
            text_summary = "\n".join(chunks)[:8000]
        except Exception:
            text_summary = "[PDF file; could not extract text reliably]"
    else:
        # Fallback: try decode as text
        try:
            text_summary = data.decode("utf-8", errors="replace")
        except Exception:
            text_summary = f"[Binary file of type {content_type}; length={len(data)}]"

    return text_summary


def pick_data_file_links(
    quiz_url: str,
    page_text: str,
    links: List[str],
) -> List[str]:
    """
    Choose which links look like data files worth downloading.
    We'll pick ones that end with .csv, .json, .txt, .pdf, etc.
    """
    exts = (".csv", ".json", ".txt", ".tsv", ".pdf")
    chosen: List[str] = []
    for link in links:
        if any(link.lower().endswith(ext) for ext in exts):
            chosen.append(urljoin(quiz_url, link))
    return sorted(set(chosen))


# ---------------------------------------------------------
# 4. Solve a single quiz page
# ---------------------------------------------------------

async def solve_single_quiz(
    quiz_url: str,
    student_email: str,
    student_secret: str,
) -> Dict[str, Any]:
    """
    Solve a single quiz page:
      - Fetch quiz page
      - Extract instructions and data files
      - Ask LLM for 'answer'
      - Submit answer to submit URL, follow next URL if provided
    """

    html, page_text, links = await fetch_quiz_page(quiz_url)
    instructions = extract_quiz_instructions(page_text)
    submit_url = find_submit_url(quiz_url, page_text, links, html)

    # Fallback: if still missing, use origin + "/submit"
    if not submit_url:
        parsed = urlparse(quiz_url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            submit_url = urljoin(origin, "/submit")
        else:
            raise RuntimeError(f"Could not find submit URL on quiz page: {quiz_url}")

    # Figure out which data files to download
    data_file_urls = pick_data_file_links(quiz_url, page_text, links)
    data_files: List[Dict[str, Any]] = []

    for u in data_file_urls:
        try:
            text_summary = await download_and_extract_file_text(u)
            data_files.append(
                {
                    "url": u,
                    "content_type": "unknown",
                    "text_snippet": text_summary[:8000],
                }
            )
        except Exception as e:
            data_files.append(
                {
                    "url": u,
                    "content_type": "error",
                    "text_snippet": f"Error downloading file: {e}",
                }
            )

    # Ask LLM to compute the answer
    answer = await ask_llm_for_answer(
        quiz_url=quiz_url,
        page_text=page_text,
        quiz_instructions=instructions,
        data_files=data_files,
    )

    # Build submit payload (prefer using template from page)
    template = extract_submission_template(page_text)
    if template:
        submit_payload: Dict[str, Any] = dict(template)
        submit_payload["email"] = student_email
        submit_payload["secret"] = student_secret
        submit_payload["url"] = quiz_url
        submit_payload["answer"] = answer
    else:
        submit_payload = {
            "email": student_email,
            "secret": student_secret,
            "url": quiz_url,
            "answer": answer,
        }

    # Actually call the submit URL
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http_client:
        submit_resp = await http_client.post(submit_url, json=submit_payload)
        # We want to see error messages, so let 4xx raise
        submit_resp.raise_for_status()
        try:
            resp_json = submit_resp.json()
        except Exception:
            resp_json = {"raw": submit_resp.text}

    return {
        "quiz_url": quiz_url,
        "answer": answer,
        "submit_url": submit_url,
        "submit_payload": submit_payload,
        "submit_response": resp_json,
        "next_url": resp_json.get("url"),
    }


# ---------------------------------------------------------
# 5. Loop over quiz chain
# ---------------------------------------------------------

async def run_quiz_chain(
    quiz_url: str,
    email: str,
    secret: str,
    max_steps: int = 5,
) -> Dict[str, Any]:
    """
    Repeatedly solve quizzes starting from quiz_url, following
    'next_url' in each submit response, up to max_steps.
    """
    results: List[Dict[str, Any]] = []
    current_url: Optional[str] = quiz_url

    for step in range(max_steps):
        if not current_url:
            break

        try:
            step_result = await solve_single_quiz(
                quiz_url=current_url,
                student_email=email,
                student_secret=secret,
            )
        except Exception as e:
            results.append(
                {
                    "quiz_url": current_url,
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            break

        results.append(step_result)
        current_url = step_result.get("next_url")

        # If no next URL, quiz is over
        if not current_url:
            break

    return {
        "start_url": quiz_url,
        "steps_taken": len(results),
        "results": results,
    }
