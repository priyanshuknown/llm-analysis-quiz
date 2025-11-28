# config.py
"""
Configuration for TDS LLM Analysis Quiz project.

We read values from environment variables so they are not hard-coded in code:
- TDS_EMAIL      -> your IITM email (e.g. 24f2005365@ds.study.iitm.ac.in)
- TDS_SECRET     -> the secret you submitted in the Google Form
- OPENAI_API_KEY -> your OpenAI API key (starts with 'sk-')

Set these in your OS before running the app.
"""

import os


EMAIL = os.environ.get("24f2005365@ds.study.iitm.ac.in")
SECRET = os.environ.get("UNKNOWN")
OPENAI_API_KEY = os.environ.get("eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjI0ZjIwMDUzNjVAZHMuc3R1ZHkuaWl0bS5hYy5pbiJ9.jTSZ0cfZb5tDCakKTBeEFjM8K5gmBPTqP-Ku39MbkPw")


def validate_config():
    """
    Make sure all required environment variables are set.
    This runs at startup so you get clear error if something is missing.
    """
    missing = []
    if not EMAIL:
        missing.append("24f2005365@ds.study.iitm.ac.in")
    if not SECRET:
        missing.append("UNKNOWN")
    if not OPENAI_API_KEY:
        missing.append("eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjI0ZjIwMDUzNjVAZHMuc3R1ZHkuaWl0bS5hYy5pbiJ9.jTSZ0cfZb5tDCakKTBeEFjM8K5gmBPTqP-Ku39MbkPw")

    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
        )
