# TDS Project 2 — LLM Analysis Quiz Solver

This project implements an HTTPS endpoint that automatically solves quiz tasks from the
TDS LLM Analysis system. It follows all requirements given in the project statement.

---

## 🚀 Features Implemented
- Accepts POST requests at `/run-quiz`
- Extracts:
  - email
  - secret
  - start quiz URL
- Fetches quiz pages using `httpx` (HTML GET requests)
- Extracts:
  - raw HTML
  - page text
  - hyperlinks
- Identifies submit URL on each page
- Generates answers using **Gemini API**
- Submits answers to the TDS quiz engine
- Handles multiple chained quiz steps
- Logs errors **without crashing**
- Always returns a clean JSON response

---

## 🧰 Tech Stack
- **FastAPI**
- **httpx (async)**
- **Google Gemini API (gemini-2.0-flash / gemini-pro-latest)**
- **Uvicorn**
- No Playwright → fully HTTP-based → suitable for Render

---

## 📡 API Endpoint
### `POST /run-quiz`

Example request body:
```json
{
  "email": "24f2005365@ds.study.iitm.ac.in",
  "secret": "PCH427LLMSECRET",
  "url": "https://tds-llm-analysis.s-anand.net/demo"
}


🔑 Environment Variables

Set your Gemini API key:

GEMINI_API_KEY=YOUR_KEY_HERE


On Render → Environment → Add Env Var.

▶️ Run Locally
pip install -r requirements.txt
uvicorn main:app --reload --port 8000


Test:

python test_request.py
