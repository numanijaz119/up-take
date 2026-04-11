@echo off
:: Up-take local start for Windows
:: Requires: Python 3.12+, PostgreSQL + Redis running

echo === Up-take Local Start ===

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

pip install -q -r requirements.txt
python -m playwright install chromium

if not exist ".env" (
    copy .env.example .env
    echo Created .env - fill in your ANTHROPIC_API_KEY
)

echo Starting Up-take on http://localhost:8000
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
