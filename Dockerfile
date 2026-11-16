FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY backend/data/puzzles.sqlite backend/data/puzzles.sqlite
COPY backend/content/levels backend/content/levels
COPY backend/content/templates backend/content/templates
COPY backend/scripts/generate_bank.py backend/scripts/review_content.py backend/scripts/
COPY frontend/index.html frontend/index.html
COPY frontend/css frontend/css
COPY frontend/js frontend/js

ENV PYTHONDONTWRITEBYTECODE=1
USER 10001
