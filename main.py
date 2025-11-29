# main.py
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

from quiz_solver import run_quiz_chain

# Load .env if present
load_dotenv()

STUDENT_EMAIL = os.getenv("STUDENT_EMAIL")
STUDENT_SECRET = os.getenv("STUDENT_SECRET")
MAX_QUIZ_STEPS = int(os.getenv("MAX_QUIZ_STEPS", "5"))

if not STUDENT_EMAIL or not STUDENT_SECRET:
    print("[WARN] STUDENT_EMAIL or STUDENT_SECRET is not set. Secret check will fail.")

app = FastAPI(title="TDS LLM Analysis Quiz - Grok Version")


class QuizRequest(BaseModel):
    email: str
    secret: str
    url: str


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
    if qr.secret != STUDENT_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # (Optional) you can verify email matches too
    if qr.email != STUDENT_EMAIL:
        print(f"[WARN] Request email {qr.email} != configured STUDENT_EMAIL {STUDENT_EMAIL}")

    # 4. Run quiz chain
    try:
        result = await run_quiz_chain(
            start_url=qr.url,
            student_email=STUDENT_EMAIL,
            student_secret=STUDENT_SECRET,
            max_steps=MAX_QUIZ_STEPS,
        )
    except Exception as e:
        # If something goes wrong, still return 200 but with error flag,
        # OR raise 500. The spec only says 200 for valid secret; it's okay to raise 500.
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "email": STUDENT_EMAIL,
            "steps_taken": result["steps_taken"],
            "results": result["results"],
        },
    )


@app.get("/")
async def root():
    return {"message": "TDS LLM Analysis Quiz endpoint. POST to /run-quiz."}
