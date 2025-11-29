# main.py

import os
import asyncio
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from quiz_solver import run_quiz_chain

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------

STUDENT_EMAIL = os.getenv("STUDENT_EMAIL")
STUDENT_SECRET = os.getenv("STUDENT_SECRET")

if not STUDENT_SECRET:
    print("[WARN] STUDENT_SECRET is not set. Secret verification will always fail.")
if not STUDENT_EMAIL:
    print("[WARN] STUDENT_EMAIL is not set. Email will not be checked strictly.")


# ---------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------

app = FastAPI(title="LLM Analysis Quiz Solver")

# Allow CORS just in case (not strictly needed for TDS evaluation)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QuizRequest(BaseModel):
    email: str
    secret: str
    url: str


class QuizResponse(BaseModel):
    status: str
    detail: Any | None = None


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "ok",
        "message": "LLM Analysis Quiz endpoint is running.",
    }


@app.post("/run-quiz")
async def run_quiz(payload: QuizRequest) -> Dict[str, Any]:
    """
    Main entrypoint for the TDS LLM Analysis Quiz project.

    Expects JSON:
      {
        "email": "...",
        "secret": "...",
        "url": "https://tds-llm-analysis.s-anand.net/quiz-xxx"
      }

    Returns:
      {
        "status": "ok",
        "email": "...",
        "steps_taken": n,
        "results": [...],
        ...
      }

    Or on error:
      {
        "status": "error",
        "error": "ExceptionType: message"
      }
    """

    # 1. Basic JSON is already validated by Pydantic (400 if missing fields)

    # 2. Verify secret
    if STUDENT_SECRET and payload.secret != STUDENT_SECRET:
        # Incorrect secret => 403 as per project spec
        raise HTTPException(status_code=403, detail="Invalid secret")

    # 3. (Optional) Check email matches
    if STUDENT_EMAIL and payload.email != STUDENT_EMAIL:
        # Not strictly required to reject, but we log it
        print(
            f"[WARN] Request email {payload.email} != STUDENT_EMAIL {STUDENT_EMAIL}. "
            "Continuing anyway."
        )

    # 4. Run quiz chain
    try:
        result = await run_quiz_chain(
            quiz_url=payload.url,
            email=payload.email,
            secret=payload.secret,
            max_steps=5,
        )
        return {
            "status": "ok",
            "email": payload.email,
            **result,
        }
    except HTTPException:
        # Let explicit HTTPExceptions pass through
        raise
    except Exception as e:
        # Catch all internal errors and wrap them
        err_str = f"{type(e).__name__}: {e}"
        print("=== INTERNAL ERROR ===")
        print(err_str)
        return {
            "status": "error",
            "error": err_str,
        }
