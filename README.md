# llm-analysis-quiz
# TDS Project 2 – LLM Analysis Quiz

This project implements the API endpoint required for the
**LLM Analysis Quiz** project in the Tools in Data Science course.

The endpoint:

- Accepts POST requests with JSON payload containing:
  - `email`
  - `secret`
  - `url` (quiz URL)
- Validates JSON and secret
- Loads the quiz page in a headless browser (Playwright)
- Uses OpenAI to:
  - Understand the quiz instructions
  - Identify the submit URL
  - Construct the answer JSON
- Submits the answer to the submit URL
- Returns a JSON response

---

## 1. Setup

### 1.1 Create and activate a virtual environment (optional)

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate

# Windows (PowerShell)
.\.venv\Scripts\activate
