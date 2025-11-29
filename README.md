# TDS LLM Analysis Quiz – Grok Implementation

This FastAPI project implements the IITM TDS *LLM Analysis Quiz* endpoint using:

- FastAPI
- Playwright (headless Chromium) for JS-rendered quiz pages
- httpx for HTTP calls
- Grok (xAI API) via `xai-sdk` for reasoning and data analysis
- pandas + pypdf for basic data file handling

## 1. Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Install Chromium for Playwright
playwright install chromium
