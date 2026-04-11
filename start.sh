#!/usr/bin/env bash
# Quick-start script for local development (no Docker)
# Requires: PostgreSQL + Redis running locally, Python 3.12+

set -e

echo "=== Up-take Local Start ==="

# 1. Install dependencies
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python -m venv .venv
fi

source .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate

pip install -q -r requirements.txt

# 2. Install Playwright browsers
python -m playwright install chromium

# 3. Copy .env if not present
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in your ANTHROPIC_API_KEY"
fi

# 4. Start the app
echo "Starting Up-take on http://localhost:8000"
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
