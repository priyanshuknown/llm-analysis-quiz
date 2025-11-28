# main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool

from config import SECRET, EMAIL, validate_config
from quiz_solver import solve_quiz

# Validate config at startup
validate_config()

app = FastAPI(
    title="TDS LLM Analysis Quiz Endpoint",
    description="API endpoint for TDS Project 2: LLM Analysis Quiz",
)


@app.get("/")
def root():
    """
    Simple health-check endpoint.
    TDS probably won't use this, but it's useful for you.
    """
    return {"status": "ok", "message": "LLM Analysis Quiz endpoint is running"}


@app.post("/")
async def handle_quiz(request: Request):
    """
    Main POST endpoint.

    Behaviour required by project spec:
    - Invalid JSON  -> HTTP 400
    - Invalid secret -> HTTP 403
    - Valid secret   -> HTTP 200 with JSON payload
    """
    # 1. Parse JSON
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 2. Validate secret
    incoming_secret = data.get("secret")
    if incoming_secret != SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    quiz_url = data.get("url")
    if not quiz_url:
        raise HTTPException(status_code=400, detail="Missing 'url' field")

    # 3. Call quiz solver in a separate thread (Playwright is blocking)
    result = await run_in_threadpool(solve_quiz, quiz_url, data, EMAIL, SECRET)

    # 4. For valid secrets, always HTTP 200
    return JSONResponse(result, status_code=200)
