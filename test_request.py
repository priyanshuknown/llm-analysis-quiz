import requests

payload = {
    "email": "24f2005365@ds.study.iitm.ac.in",
    "secret": "UNKNOWN",  # same as in .env
    "url": "https://tds-llm-analysis.s-anand.net/demo",
}


resp = requests.post("http://127.0.0.1:8000/run-quiz", json=payload)
print("Status:", resp.status_code)
try:
    print("Response:", resp.json())
except Exception:
    print("Raw response text:", resp.text)