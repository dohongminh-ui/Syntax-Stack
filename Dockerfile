FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY backend/data/puzzles.sqlite backend/data/puzzles.sqlite
COPY backend/content/levels backend/content/levels
COPY backend/content/templates backend/content/templates
# mistake notes and short labels: used by the live-classroom dashboard at runtime
COPY backend/content/mistakes.yaml backend/content/mistake_labels.yaml backend/content/
# generated nicknames and the free-name blocklist: loaded at import time
COPY backend/content/nickname_words.yaml backend/content/name_blocklist.yaml backend/content/
COPY backend/scripts/generate_bank.py backend/scripts/review_content.py backend/scripts/
COPY frontend/index.html frontend/index.html
COPY frontend/*.png frontend/favicon.ico frontend/favicon.svg frontend/manifest.json frontend/robots.txt frontend/sitemap.xml frontend/
COPY frontend/css frontend/css
COPY frontend/js frontend/js

# Learner-made puzzle sets live outside the image (compose mounts a named volume here) so shared links
# survive redeploys. backend/data stays writable as the fallback when no volume is mounted.
RUN mkdir -p /var/lib/syntax-stack && chown 10001 /var/lib/syntax-stack backend/data
ENV SYNTAX_STACK_CUSTOM_DB=/var/lib/syntax-stack/custom.sqlite

ENV PYTHONDONTWRITEBYTECODE=1
USER 10001
