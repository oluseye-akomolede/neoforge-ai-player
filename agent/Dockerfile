# ── Stage 1: Build frontend SPA ──
FROM node:20-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --ignore-scripts
COPY frontend/ .
RUN npm run build

# ── Stage 2: Python agent + dashboard ──
FROM python:3.11-slim

WORKDIR /opt/aibot-agent

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/static ./static

ENV PYTHONUNBUFFERED=1

CMD ["python3", "agent.py"]
