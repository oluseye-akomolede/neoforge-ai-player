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

# Tests are development artefacts and have no business in a runtime image: they
# add surface nobody executes, and nothing in the tree imports them, so their
# absence is not observable at run time (review 2026-11-12).
#
# Three globs because the tree uses three namings, and the first version of this
# line used only the first: test_*.py at the top level (9 files), *_test.py at
# the top level (rl_reward_test.py, task_d_fixes_test.py), and tests/. A single
# `rm -f ./test_*.py` leaves ten test files in the image while the comment says
# there are none - a claim and an artefact with nothing comparing them. Measured
# on a clean export: 15 test files -> 0.
RUN rm -rf ./tests && rm -f ./test_*.py ./*_test.py

ENV PYTHONUNBUFFERED=1

CMD ["python3", "agent.py"]
