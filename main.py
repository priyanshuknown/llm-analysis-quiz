# main.py
import os
import traceback
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

# Load .env BEFORE importing quiz_solver
load_dotenv()

from quiz_solver import run_quiz_chain  # noqa: E402

STUDENT_EMAIL = os.getenv("STUDENT_EMAIL")
STUDENT_SECRET = os.getenv("STUDENT_SECRET")
MAX_QUIZ_STEPS = int(os.getenv("MAX_QUIZ_STEPS", "5"))

if not STUDENT_SECRET:
    print("[WARN] STUDENT_SECRET is not set. Secret verification will fail.")
if not STUDENT_EMAIL:
    print("[WARN] STUDENT_EMAIL is not set. Using request email instead for submissions.")

app = FastAPI(title="TDS LLM Analysis Quiz – Gemini Version")


class QuizRequest(BaseModel):
    email: str
    secret: str
    url: str


@app.get("/")
async def root():
    return {"message": "TDS LLM Analysis Quiz endpoint. POST to /run-quiz."}


@app.post("/run-quiz")
async def run_quiz(request: Request):
    # 1. Parse JSON safely
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 2. Validate schema
    try:
        qr = QuizRequest(**body)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON fields: {e.errors()}")

    # 3. Verify secret
    if STUDENT_SECRET is None:
        raise HTTPException(status_code=500, detail="Server misconfigured: STUDENT_SECRET not set")

    if qr.secret != STUDENT_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # We can optionally check email, but spec only requires secret verification
    student_email = STUDENT_EMAIL or qr.email
    student_secret = STUDENT_SECRET

    # 4. Run quiz chain
    try:
        result = await run_quiz_chain(
            start_url=qr.url,
            student_email=student_email,
            student_secret=student_secret,
            max_steps=MAX_QUIZ_STEPS,
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "email": student_email,
                "steps_taken": result["steps_taken"],
                "results": result["results"],
            },
        )
    except Exception as e:
        tb = traceback.format_exc()
        print("=== INTERNAL ERROR ===")
        print(tb)
        # Per spec: secret is valid → still return HTTP 200 JSON
        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            },
        )
