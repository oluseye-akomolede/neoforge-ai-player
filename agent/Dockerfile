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

# Scripts and bindings are delivered as a ConfigMap at run time (SCRIPTS_DIR),
# never baked in. The repo copies are the source the ConfigMap is generated
# from, not a runtime default: an image-local bindings.json silently binds the
# wrong file whenever the mount is missing, which is the failure this removal
# makes impossible rather than merely unlikely (review 2026-11-11, C1).
RUN rm -rf ./scripts

ENV PYTHONUNBUFFERED=1

CMD ["python3", "agent.py"]
